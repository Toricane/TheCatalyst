"""AI interaction helpers for The Catalyst backend."""

from __future__ import annotations

import ast
import asyncio
import hashlib
import json
import random
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import (
    ALT_MODEL_NAME,
    ENVELOPE_FORMAT,
    MODEL_NAME,
    SHOW_THINKING,
    SYSTEM_PROMPT_PATH,
)
from .context_serializer import build_context_block, context_format_metadata
from .envelope_codec import (
    GREETING_OUTPUT_INSTRUCTIONS,
    format_output_instructions,
    parse_envelope,
)
from .functions import apply_envelope_actions, catalyst_functions
from .llm_client import acompletion, is_configured
from .memory_manager import extract_section
from .models import LTMProfile
from .rate_limiter import estimate_tokens, rate_limiter
from .schemas import SessionType
from .time_utils import local_now

# Retry configuration
MAX_RETRIES = 4
BASE_DELAY = 1.0  # Base delay in seconds
MAX_DELAY = 60.0  # Maximum delay in seconds
JITTER_RANGE = 0.1  # Jitter factor for randomization

DEFAULT_FALLBACK_RESPONSE = "I'm here and ready to help you achieve your goals."
SAFETY_FALLBACK_RESPONSE = (
    "I want to keep our momentum strong, but the model flagged the last request for "
    "safety reasons. Let's try reframing it or shifting to a different angle."
)

OutputMode = Literal["structured", "greeting", "plain"]

# Re-export for backwards-compatible test imports
_parse_structured_envelope = parse_envelope

_api_request_log_count = 0

def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable (503 overload / connection errors)."""
    error_str = str(error).lower()
    return (
        "503" in error_str
        or "502" in error_str
        or "504" in error_str
        or "overloaded" in error_str
        or "unavailable" in error_str
        or "try again later" in error_str
        or "connection" in error_str
    )


@dataclass
class QuotaErrorInfo:
    status_code: int
    message: str
    retry_after: Optional[float]


def _parse_quota_error(error: Exception) -> Optional[QuotaErrorInfo]:
    """Extract structured information from API quota (429) errors."""

    status_code: Optional[int] = getattr(error, "status_code", None)
    payload: Optional[Dict[str, Any]] = getattr(error, "response", None)

    if status_code is None:
        match = re.search(r"\b(\d{3})\b", str(error))
        if match:
            status_code = int(match.group(1))

    if status_code != 429:
        return None

    error_message: Optional[str] = None
    retry_after: Optional[float] = None

    if isinstance(payload, dict):
        error_payload = payload.get("error")
    else:
        error_payload = None

    if error_payload is None and "{" in str(error):
        try:
            raw_payload = str(error)[str(error).index("{") :]
            parsed_payload = json.loads(raw_payload)
        except (ValueError, json.JSONDecodeError):
            try:
                parsed_payload = ast.literal_eval(raw_payload)
            except (SyntaxError, ValueError):
                parsed_payload = None
        if isinstance(parsed_payload, dict):
            error_payload = parsed_payload.get("error")

    if isinstance(error_payload, dict):
        error_message = error_payload.get("message") or error_message
        details = error_payload.get("details", [])
        for detail in details:
            if not isinstance(detail, dict):
                continue
            retry_delay_value = detail.get("retryDelay") or detail.get("retry_delay")
            if detail.get("@type", "").endswith("RetryInfo") and retry_delay_value:
                if isinstance(retry_delay_value, (int, float)):
                    retry_after = float(retry_delay_value)
                elif isinstance(retry_delay_value, str):
                    match = re.match(r"([0-9]+(?:\.[0-9]+)?)s", retry_delay_value)
                    if match:
                        retry_after = float(match.group(1))
            if retry_after is None:
                violations = detail.get("violations")
                if isinstance(violations, list):
                    for violation in violations:
                        if not isinstance(violation, dict):
                            continue
                        hint = violation.get("description") or violation.get("message")
                        if hint and retry_after is None:
                            match = re.search(
                                r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", hint.lower()
                            )
                            if match:
                                retry_after = float(match.group(1))

    if retry_after is None:
        match = re.search(r"retry in\s+([0-9]+(?:\.[0-9]+)?)s", str(error).lower())
        if match:
            retry_after = float(match.group(1))

    message = error_message or "API quota exceeded."
    return QuotaErrorInfo(status_code=429, message=message, retry_after=retry_after)


def _calculate_retry_delay(attempt: int) -> float:
    """Calculate exponential backoff delay with jitter."""
    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
    jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE) * delay
    return max(0.1, delay + jitter)


async def _make_api_call_with_retry(
    model: str,
    messages: List[Dict[str, Any]],
    *,
    tools: Optional[List[Dict[str, Any]]] = None,
    temperature: float = 0.7,
    estimated_prompt_tokens: int,
    context: str = "initial",
    response_format: Optional[Dict[str, str]] = None,
) -> Tuple[Any, str]:
    """Make API call with retry logic, rate limiting, and model fallback."""
    global _api_request_log_count
    last_error = None
    primary_model = model
    fallback_model = ALT_MODEL_NAME if ALT_MODEL_NAME != primary_model else None
    last_was_retryable = False

    for attempt in range(MAX_RETRIES):
        current_model = primary_model
        switched_due_to_limit = False

        if attempt > 0 and fallback_model:
            if last_was_retryable:
                current_model = fallback_model
                print(
                    f"↪️  Switching to fallback model '{current_model}' for {context} "
                    "call after primary failure"
                )
            else:
                wait_primary = await rate_limiter.get_wait_time(
                    primary_model, estimated_prompt_tokens
                )
                wait_fallback = await rate_limiter.get_wait_time(
                    fallback_model, estimated_prompt_tokens
                )

                if wait_primary > 0:
                    if wait_fallback == 0 or wait_fallback <= wait_primary:
                        current_model = fallback_model
                        switched_due_to_limit = True
        elif attempt > 0 and not fallback_model:
            pass

        if attempt == 0 and fallback_model:
            wait_primary = await rate_limiter.get_wait_time(
                primary_model, estimated_prompt_tokens
            )
            if wait_primary > 0:
                wait_fallback = await rate_limiter.get_wait_time(
                    fallback_model, estimated_prompt_tokens
                )
                if wait_fallback == 0:
                    current_model = fallback_model
                    switched_due_to_limit = True

        if switched_due_to_limit:
            print(
                f"↪️  Switching to fallback model '{current_model}' for {context} call due to rate limit"
            )

        await rate_limiter.wait_for_request(current_model, estimated_prompt_tokens)

        try:
            if attempt > 0:
                print(
                    f"🔄 Retry attempt {attempt + 1}/{MAX_RETRIES} for {context} call (using {current_model})"
                )

            response = await acompletion(
                model=current_model,
                messages=messages,
                tools=tools,
                temperature=temperature,
                response_format=response_format,
            )

            _api_request_log_count += 1
            print(
                f"📡 API request #{_api_request_log_count} "
                f"context={context} model={current_model}"
            )

            if attempt > 0:
                print(
                    f"✅ {context.capitalize()} call succeeded on attempt {attempt + 1}"
                )

            last_was_retryable = False
            return response, current_model

        except Exception as exc:
            quota_info: Optional[QuotaErrorInfo] = _parse_quota_error(exc)

            await rate_limiter.record_usage(current_model, 0)

            if quota_info and quota_info.retry_after:
                await rate_limiter.register_backoff(
                    current_model, quota_info.retry_after
                )

            if quota_info:
                last_error = HTTPException(
                    status_code=quota_info.status_code,
                    detail={
                        "error": "API quota exceeded",
                        "model": current_model,
                        "message": quota_info.message,
                        "retry_after_seconds": quota_info.retry_after,
                    },
                )
                print(
                    f"🚫 {context.capitalize()} call hit quota limit on {current_model}: {quota_info.message}"
                )
                last_was_retryable = False
                if attempt < MAX_RETRIES - 1:
                    continue
                raise last_error

            last_error = exc
            last_was_retryable = _is_retryable_error(exc)

            if not last_was_retryable:
                raise exc

            if attempt < MAX_RETRIES - 1:
                delay = _calculate_retry_delay(attempt)
                print(
                    f"⚠️  {context.capitalize()} call failed (attempt {attempt + 1}/{MAX_RETRIES}): {exc}"
                )
                print(f"⏳ Waiting {delay:.1f}s before retry...")
                await asyncio.sleep(delay)
            else:
                print(f"❌ All retry attempts failed for {context} call")

    if isinstance(last_error, HTTPException):
        raise last_error

    raise HTTPException(
        status_code=503,
        detail=(
            f"AI service temporarily unavailable after {MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        ),
    ) from last_error


async def generate_catalyst_response(
    message: str,
    session_type: SessionType,
    context: Dict[str, Any],
    *,
    primary_model: str = MODEL_NAME,
    output_mode: OutputMode = "structured",
) -> Dict[str, Any]:
    """Generate a response from the Catalyst AI agent (single API request per call)."""
    if not is_configured():
        raise HTTPException(
            status_code=500,
            detail="AI client not configured; missing CLOD_API_KEY",
        )

    base_prompt_text, base_metadata = _load_base_prompt()
    prompt_timestamp = local_now()
    context_block = build_context_block(context, session_type, prompt_timestamp)
    context_meta = context_format_metadata(context_block)
    system_prompt = _build_system_prompt(
        session_type,
        context,
        base_prompt=base_prompt_text,
        generated_at=prompt_timestamp,
        output_mode=output_mode,
        context_block=context_block,
    )
    try:
        context_snapshot = json.loads(json.dumps(context, default=str))
    except TypeError:  # pragma: no cover - fallback for unexpected types
        context_snapshot = context

    conversation: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ]
    temperature = 0.7
    estimated_tokens = estimate_tokens(system_prompt, message)

    response_format: Optional[Dict[str, str]] = None
    if (
        output_mode == "structured"
        and primary_model.startswith("gemini-")
        and ENVELOPE_FORMAT == "json"
    ):
        response_format = {"type": "json_object"}

    response, current_model_used = await _make_api_call_with_retry(
        primary_model,
        conversation,
        tools=None,
        temperature=temperature,
        estimated_prompt_tokens=estimated_tokens,
        context=output_mode,
        response_format=response_format,
    )

    raw_text = _extract_response_text(response)
    executed_calls: List[Dict[str, Any]] = []
    memory_updated = False

    if output_mode == "structured":
        response_text, envelope = parse_envelope(raw_text)
        if not response_text:
            response_text = _derive_fallback_message(response)
        else:
            executed_calls, memory_updated = apply_envelope_actions(envelope)
    else:
        response_text = raw_text
        if not response_text:
            debug_summary = _summarize_empty_response(response)
            print(
                "⚠️  Model returned empty response for catalyst reply. "
                f"Summary: {debug_summary}"
            )
            response_text = (
                _greeting_fallback(context, session_type)
                if output_mode == "greeting"
                else _derive_fallback_message(response)
            )
            await rate_limiter.record_usage(current_model_used, 0)
        else:
            actual_tokens = estimate_tokens(response_text)
            await rate_limiter.record_usage(current_model_used, actual_tokens)

    if output_mode == "structured" and response_text:
        actual_tokens = estimate_tokens(response_text)
        await rate_limiter.record_usage(current_model_used, actual_tokens)

    result = {
        "response": response_text,
        "memory_updated": memory_updated,
        "function_calls": executed_calls,
        "thinking": json.dumps(executed_calls) if SHOW_THINKING else None,
        "model": current_model_used,
    }

    result["system_prompt"] = system_prompt
    result["context_snapshot"] = context_snapshot
    result["system_prompt_reference"] = {
        "type": "system_prompt/v1",
        "session_type": session_type.value,
        "generated_at": prompt_timestamp.isoformat(),
        "base": base_metadata,
        **context_meta,
    }

    return result


async def update_ltm_memory(
    user_message: str, ai_response: str, context: Dict[str, Any], session: Session
) -> bool:
    """Request a memory synthesis update from the primary model."""
    if not is_configured():
        raise HTTPException(
            status_code=500,
            detail="AI client not configured; missing CLOD_API_KEY",
        )

    if SYSTEM_PROMPT_PATH.exists():
        base_profile_text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    else:
        base_profile_text = "You are a memory synthesis system."

    synthesis_prompt = f"""
    Based on today's conversation and the existing user profile, create an updated memory synthesis.

    Current Profile:
    {context["ltm_profile"]["full_text"]}

    Today's Exchange:
    User: {user_message}
    Catalyst: {ai_response}

    Create an updated profile that:
    1. Integrates new insights from today
    2. Identifies emerging patterns
    3. Updates current state and momentum
    4. Compresses older information if needed (target: ~1500 tokens total)
    5. Maintains these sections:
       - Overview & North Star
       - Key Patterns
       - Recurring Challenges
       - Breakthroughs & Wins
       - Personality Traits
       - Current State & Momentum
     6. Format each section with a Markdown H2 heading (e.g., "## Key Patterns") matching the names above exactly.

    Be concise but insightful. Focus on what will be most useful for future interactions.
    """

    messages = [
        {"role": "system", "content": base_profile_text},
        {"role": "user", "content": synthesis_prompt},
    ]

    estimated_tokens = estimate_tokens(synthesis_prompt, base_profile_text)

    try:
        response, model_used = await _make_api_call_with_retry(
            MODEL_NAME,
            messages,
            temperature=0.3,
            estimated_prompt_tokens=estimated_tokens,
            context="ltm-synthesis",
        )
    except Exception as exc:  # pragma: no cover
        print(f"Error updating LTM: {exc}")
        return False

    new_profile = _extract_response_text(response)

    memory_tokens = estimate_tokens(new_profile)
    await rate_limiter.record_usage(model_used, memory_tokens)

    sections = {
        "patterns": extract_section(new_profile, "Patterns"),
        "challenges": extract_section(new_profile, "Challenges"),
        "breakthroughs": extract_section(new_profile, "Breakthroughs"),
        "personality": extract_section(new_profile, "Personality"),
        "current_state": extract_section(new_profile, "Current State"),
    }

    current_version = session.query(func.max(LTMProfile.version)).scalar() or 0
    new_profile_entry = LTMProfile(
        summary_text=new_profile,
        patterns_section=sections["patterns"],
        challenges_section=sections["challenges"],
        breakthroughs_section=sections["breakthroughs"],
        personality_section=sections["personality"],
        current_state_section=sections["current_state"],
        version=current_version + 1,
        token_count=len(new_profile.split()),
    )

    session.add(new_profile_entry)

    return True


def get_session_instructions(session_type: SessionType) -> str:
    """Return session-specific guidance for the AI."""
    instructions = {
        SessionType.MORNING: """
        **Morning Ignition Protocol**:
        1. Acknowledge their presence with energy
        2. State their North Star goal clearly
        3. Ask about their energy and readiness
        4. Help them set 1-3 concrete intentions for the day
        5. End with a powerful, motivating challenge
        Keep it brief (5 minutes max) but impactful.
        """,
        SessionType.EVENING: """
        **Evening Reflection Protocol**:
        1. Welcome them back, acknowledge the day's effort
        2. Ask them to share wins (celebrate these genuinely)
        3. Explore challenges with curiosity, not judgment
        4. Guide them to find gratitude (even in difficulty)
        5. Help identify key lessons and patterns
        6. Set tomorrow's top priority together
        7. IMPORTANT: Synthesize insights for memory update
        This is deeper work (10-15 minutes) - be thorough.
        """,
        SessionType.CATCH_UP: """
        **Catch-Up Recovery Protocol**:
        1. No judgment about missed sessions - life happens
        2. Quick check on overall state and energy
        3. Focus on the most important recent development
        4. Rapidly identify what needs immediate attention
        5. Reset momentum with one clear next action
        Keep it supportive but action-oriented.
        """,
        SessionType.GENERAL: """
        **General Interaction Mode**:
        - Be responsive to their needs
        - Default to Tough Coach unless context suggests otherwise
        - Always connect conversation back to their goals
        - Look for opportunities to reinforce positive patterns
        """,
        SessionType.INITIALIZATION: """
        **Initialization Protocol**:
        1. **Grounded Welcome** — acknowledge the decision with weight and respect. Signal importance without exaggeration.
        2. **Clarify Goal** — help the user state their goal clearly, in their own words.
        3. **Make it Measurable** — ensure the metric is specific and trackable.
        4. **Check the Timeline** — confirm it's ambitious but achievable.
        5. **Commitment Statement** — end with a clear, concise declaration: this is the starting point, momentum begins now.
        This sets the tone for everything - make it count.
        """,
    }
    return instructions.get(session_type, instructions[SessionType.GENERAL])


def _load_base_prompt() -> Tuple[str, Dict[str, Any]]:
    """Load the base system prompt text along with metadata."""

    if SYSTEM_PROMPT_PATH.exists():
        try:
            text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
        except OSError:
            text = "You are The Catalyst, an elite AI mentor."
            metadata = {
                "source": "default",
                "path": None,
                "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "length": len(text),
                "modified_at": None,
            }
            return text, metadata

        checksum = hashlib.sha256(text.encode("utf-8")).hexdigest()
        try:
            stat = SYSTEM_PROMPT_PATH.stat()
            modified_at = datetime.fromtimestamp(
                stat.st_mtime, timezone.utc
            ).isoformat()
        except OSError:
            modified_at = None

        metadata = {
            "source": "file",
            "path": str(SYSTEM_PROMPT_PATH.resolve()),
            "checksum": checksum,
            "length": len(text),
            "modified_at": modified_at,
        }
        return text, metadata

    text = "You are The Catalyst, an elite AI mentor."
    metadata = {
        "source": "default",
        "path": None,
        "checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "length": len(text),
        "modified_at": None,
    }
    return text, metadata


def _build_system_prompt(
    session_type: SessionType,
    context: Dict[str, Any],
    *,
    base_prompt: Optional[str] = None,
    generated_at: Optional[datetime] = None,
    output_mode: OutputMode = "structured",
    context_block: Optional[str] = None,
) -> str:
    if base_prompt is None:
        base_prompt, _ = _load_base_prompt()

    timestamp_source = generated_at or local_now()
    if context_block is None:
        context_block = build_context_block(context, session_type, timestamp_source)

    prompt = (
        f"{base_prompt}\n\n{context_block}\n\n"
        f"## Session-Specific Instructions:\n\n{get_session_instructions(session_type)}\n"
    )

    if output_mode == "structured":
        prompt += f"\n{format_output_instructions()}\n"
    elif output_mode == "greeting":
        prompt += f"\n{GREETING_OUTPUT_INSTRUCTIONS}\n"

    return prompt


def _greeting_fallback(context: Dict[str, Any], session_type: SessionType) -> str:
    goals = context.get("goals") or []
    goal_text = goals[0].get("description", "your North Star") if goals else "your North Star"
    hour = local_now().hour
    if 4 <= hour < 12:
        period = "morning"
    elif hour >= 20 or hour < 4:
        period = "evening"
    else:
        period = "day"
    return (
        f"Good {period}. Your North Star: {goal_text}. "
        "What's the one move that matters most right now?"
    )


def _parse_reference_timestamp(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    normalised = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalised)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def reconstruct_system_prompt(
    session_type: SessionType,
    context: Dict[str, Any],
    reference: Optional[Dict[str, Any]] = None,
) -> Tuple[str, Dict[str, Any]]:
    base_prompt_text, runtime_metadata = _load_base_prompt()
    generated_at = None
    if reference:
        generated_at = _parse_reference_timestamp(reference.get("generated_at"))

    prompt = _build_system_prompt(
        session_type,
        context,
        base_prompt=base_prompt_text,
        generated_at=generated_at,
    )

    return prompt, runtime_metadata


def _append_assistant_message(
    conversation: List[Dict[str, Any]], response: Any
) -> None:
    """Append the assistant turn (including tool calls) to the conversation."""

    if not getattr(response, "choices", None):
        return

    message = response.choices[0].message
    entry: Dict[str, Any] = {
        "role": "assistant",
        "content": message.content or "",
    }
    if message.tool_calls:
        entry["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments,
                },
            }
            for tc in message.tool_calls
        ]
    conversation.append(entry)


def _extract_function_calls(
    response: Any,
) -> List[Tuple[str, Dict[str, Any], str]]:
    calls: List[Tuple[str, Dict[str, Any], str]] = []
    if not getattr(response, "choices", None):
        return calls

    message = response.choices[0].message
    if not message.tool_calls:
        return calls

    for tool_call in message.tool_calls:
        args = _normalise_args(tool_call.function.arguments)
        calls.append((tool_call.function.name, args, tool_call.id))

    return calls


def _extract_response_text(response: Any) -> str:
    if not getattr(response, "choices", None):
        return ""

    message = response.choices[0].message
    content = getattr(message, "content", None)
    if content:
        return str(content).strip()
    return ""


def _summarize_empty_response(response: Any) -> str:
    if not getattr(response, "choices", None):
        return json.dumps({"choices": []})

    choice = response.choices[0]
    message = choice.message
    debug_payload = {
        "finish_reason": getattr(choice, "finish_reason", None),
        "has_tool_calls": bool(getattr(message, "tool_calls", None)),
        "refusal": getattr(message, "refusal", None),
    }

    try:
        return json.dumps(debug_payload)
    except TypeError:
        return str(debug_payload)


def _derive_fallback_message(response: Any) -> str:
    if not getattr(response, "choices", None):
        return DEFAULT_FALLBACK_RESPONSE

    message = response.choices[0].message
    finish_reason = getattr(response.choices[0], "finish_reason", None)
    if finish_reason and str(finish_reason).lower() in {"content_filter", "safety"}:
        return SAFETY_FALLBACK_RESPONSE

    refusal = getattr(message, "refusal", None)
    if refusal:
        return SAFETY_FALLBACK_RESPONSE

    return DEFAULT_FALLBACK_RESPONSE


def _should_retry_due_to_empty_response(response: Any) -> bool:
    if _extract_function_calls(response):
        # Empty text is expected when the model is requesting a tool call.
        return False
    return not _extract_response_text(response)


async def _retry_once_if_empty(
    response: Any,
    model_used: str,
    *,
    primary_model: str,
    fallback_model: Optional[str],
    conversation: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]],
    temperature: float,
    estimated_tokens: int,
    context: str,
) -> Tuple[Any, str, bool]:
    if not _should_retry_due_to_empty_response(response):
        return response, model_used, False

    debug_summary = _summarize_empty_response(response)
    print(
        "⚠️  Model returned empty response (will retry once). "
        f"Context: {context}. Summary: {debug_summary}"
    )

    await rate_limiter.record_usage(model_used, 0)

    retry_model = primary_model
    retry_context = f"{context}-retry"
    if fallback_model and fallback_model != model_used:
        retry_model = fallback_model
        retry_context = f"{context}-fallback"
        print(
            f"↪️  Switching to fallback model '{retry_model}' after empty response"
        )

    new_response, new_model_used = await _make_api_call_with_retry(
        retry_model,
        conversation,
        tools=tools,
        temperature=temperature,
        estimated_prompt_tokens=estimated_tokens,
        context=retry_context,
    )

    return new_response, new_model_used, True


def _normalise_args(raw_args: Any) -> Dict[str, Any]:
    if raw_args is None:
        return {}
    if isinstance(raw_args, dict):
        return raw_args
    if hasattr(raw_args, "items"):
        try:
            return dict(raw_args)
        except Exception:  # pragma: no cover - defensive
            pass
    if hasattr(raw_args, "to_dict"):
        return raw_args.to_dict()
    if hasattr(raw_args, "to_json"):
        try:
            return json.loads(raw_args.to_json())
        except Exception:  # pragma: no cover - defensive
            return {}
    if isinstance(raw_args, str):
        try:
            return json.loads(raw_args)
        except json.JSONDecodeError:
            return {"value": raw_args}
    return {}


def _execute_tool(
    name: str, args: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    call_record: Dict[str, Any] = {"function": name, "args": args}
    func = catalyst_functions.get(name)
    if func is None:
        error_msg = f"Unknown function: {name}"
        call_record["error"] = error_msg
        return {"error": error_msg}, call_record

    try:
        result = func(**args)
    except Exception as exc:  # pragma: no cover - defensive
        error_msg = str(exc)
        call_record["error"] = error_msg
        return {"error": error_msg}, call_record

    if isinstance(result, dict):
        call_record["result"] = result
        return result, call_record

    call_record["result"] = {"value": result}
    return {"value": result}, call_record


def _parse_model_response(
    response: Any,
    executed_calls: List[Dict[str, Any]],
    *,
    model_used: Optional[str] = None,
    response_text: Optional[str] = None,
) -> Dict[str, Any]:  # pragma: no cover - structure from vendor

    final_text = (
        response_text
        if response_text is not None
        else _extract_response_text(response)
    )

    if not final_text:
        final_text = DEFAULT_FALLBACK_RESPONSE

    return {
        "response": final_text,
        "memory_updated": bool(executed_calls),
        "function_calls": executed_calls,
        "thinking": json.dumps(executed_calls) if SHOW_THINKING else None,
        "model": model_used,
    }
