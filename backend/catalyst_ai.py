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
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from sqlalchemy import func
from sqlalchemy.orm import Session

from .config import (
    ALT_MODEL_NAME,
    GEMINI_API_KEY,
    MODEL_NAME,
    SHOW_THINKING,
    SYSTEM_PROMPT_PATH,
)
from .functions import catalyst_functions, create_function_definitions
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

if not GEMINI_API_KEY:
    # We don't raise immediately to allow the app to start for offline testing,
    # but we will surface a clearer error when a call is attempted.
    client: Optional[genai.Client] = None
else:
    client = genai.Client(api_key=GEMINI_API_KEY)


def _is_retryable_error(error: Exception) -> bool:
    """Check if an error is retryable (503 overload errors)."""
    error_str = str(error).lower()
    return (
        "503" in error_str
        or "overloaded" in error_str
        or "unavailable" in error_str
        or "try again later" in error_str
    )


@dataclass
class QuotaErrorInfo:
    status_code: int
    message: str
    retry_after: Optional[float]


def _parse_quota_error(error: Exception) -> Optional[QuotaErrorInfo]:
    """Extract structured information from Gemini quota errors."""

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

    message = error_message or "Gemini quota exceeded."
    return QuotaErrorInfo(status_code=429, message=message, retry_after=retry_after)


def _calculate_retry_delay(attempt: int) -> float:
    """Calculate exponential backoff delay with jitter."""
    delay = min(BASE_DELAY * (2**attempt), MAX_DELAY)
    jitter = random.uniform(-JITTER_RANGE, JITTER_RANGE) * delay
    return max(0.1, delay + jitter)


async def _make_api_call_with_retry(
    client: genai.Client,
    model: str,
    contents: List[types.Content],
    config: types.GenerateContentConfig,
    estimated_prompt_tokens: int,
    context: str = "initial",
) -> Tuple[Any, str]:
    """Make API call with retry logic, rate limiting, and model fallback."""
    last_error = None
    primary_model = model
    fallback_model = ALT_MODEL_NAME if ALT_MODEL_NAME != primary_model else None

    for attempt in range(MAX_RETRIES):
        # Determine which model to use for this attempt
        current_model = primary_model
        switched_due_to_limit = False

        if attempt > 0 and fallback_model:
            wait_primary = await rate_limiter.get_wait_time(
                primary_model, estimated_prompt_tokens
            )
            wait_fallback = await rate_limiter.get_wait_time(
                fallback_model, estimated_prompt_tokens
            )

            if wait_primary > 0:
                switched_due_to_limit = True
                # Prefer the model with the shorter wait time when possible
                if wait_fallback == 0 or wait_fallback <= wait_primary:
                    current_model = fallback_model
                else:
                    current_model = fallback_model
        elif attempt > 0 and not fallback_model:
            # No fallback available, continue with primary
            pass

        if attempt == 0 and fallback_model:
            # Initial attempt should still respect current availability
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

        # Reserve quota for the selected model (counts towards rate limits)
        await rate_limiter.wait_for_request(current_model, estimated_prompt_tokens)

        try:
            if attempt > 0:
                print(
                    f"🔄 Retry attempt {attempt + 1}/{MAX_RETRIES} for {context} call (using {current_model})"
                )

            response = await asyncio.to_thread(
                client.models.generate_content,
                model=current_model,
                contents=contents,
                config=config,
            )

            if attempt > 0:
                print(
                    f"✅ {context.capitalize()} call succeeded on attempt {attempt + 1}"
                )

            return response, current_model

        except Exception as exc:
            quota_info: Optional[QuotaErrorInfo] = None

            if isinstance(exc, genai_errors.ClientError):
                quota_info = _parse_quota_error(exc)

            # Release reserved quota since the request failed
            await rate_limiter.record_usage(current_model, 0)

            if quota_info and quota_info.retry_after:
                await rate_limiter.register_backoff(
                    current_model, quota_info.retry_after
                )

            if quota_info:
                last_error = HTTPException(
                    status_code=quota_info.status_code,
                    detail={
                        "error": "Gemini quota exceeded",
                        "model": current_model,
                        "message": quota_info.message,
                        "retry_after_seconds": quota_info.retry_after,
                    },
                )
                print(
                    f"🚫 {context.capitalize()} call hit quota limit on {current_model}: {quota_info.message}"
                )
                if attempt < MAX_RETRIES - 1:
                    continue
                raise last_error

            last_error = exc

            if not _is_retryable_error(exc):
                # Non-retryable error, fail immediately
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

    # All retries exhausted
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
) -> Dict[str, Any]:
    """Generate a response from the Catalyst AI agent."""
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="Gemini client not configured; missing GEMINI_API_KEY",
        )

    base_prompt_text, base_metadata = _load_base_prompt()
    prompt_timestamp = local_now()
    system_prompt = _build_system_prompt(
        session_type,
        context,
        base_prompt=base_prompt_text,
        generated_at=prompt_timestamp,
    )
    try:
        context_snapshot = json.loads(json.dumps(context, default=str))
    except TypeError:  # pragma: no cover - fallback for unexpected types
        context_snapshot = context

    contents = [types.Content(role="user", parts=[types.Part.from_text(text=message)])]

    try:
        function_declarations = create_function_definitions()
        tools = [types.Tool(function_declarations=function_declarations)]
    except Exception as exc:  # pragma: no cover - defensive
        print(f"⚠️  Function calling disabled due to error: {exc}")
        tools = None

    config = types.GenerateContentConfig(
        temperature=0.7,
        tools=tools,
        response_modalities=["TEXT"],
        system_instruction=system_prompt,
    )

    conversation: List[types.Content] = list(contents)
    executed_calls: List[Dict[str, Any]] = []

    # Rate limiting: estimate tokens for informed reservations
    estimated_tokens = estimate_tokens(system_prompt, message)

    # Make initial API call with retry logic
    response, current_model_used = await _make_api_call_with_retry(
        client,
        primary_model,
        conversation,
        config,
        estimated_tokens,
        "initial",
    )

    # Handle iterative tool calling if the model requests it.
    for _ in range(3):
        pending_calls = _extract_function_calls(response)
        if not pending_calls:
            break

        if response.candidates and response.candidates[0].content:
            conversation.append(response.candidates[0].content)

        tool_messages: List[types.Content] = []
        for name, args in pending_calls:
            result_payload, call_record = _execute_tool(name, args)
            executed_calls.append(call_record)
            tool_messages.append(
                types.Content(
                    role="tool",
                    parts=[
                        types.Part.from_function_response(
                            name=name,
                            response=result_payload,
                        )
                    ],
                )
            )

        conversation.extend(tool_messages)

        # Make follow-up API call with retry logic
        response, current_model_used = await _make_api_call_with_retry(
            client,
            primary_model,
            conversation,
            config,
            0,
            "follow-up",
        )
    else:
        raise HTTPException(
            status_code=500,
            detail="AI produced repeated tool calls without a final response.",
        )

    # Record actual token usage after successful response
    response_text = getattr(response, "text", "") or ""
    actual_tokens = estimate_tokens(response_text)
    await rate_limiter.record_usage(current_model_used, actual_tokens)

    result = _parse_model_response(
        response,
        executed_calls,
        model_used=current_model_used,
    )

    result["system_prompt"] = system_prompt
    result["context_snapshot"] = context_snapshot
    result["system_prompt_reference"] = {
        "type": "system_prompt/v1",
        "session_type": session_type.value,
        "generated_at": prompt_timestamp.isoformat(),
        "base": base_metadata,
    }

    return result


async def update_ltm_memory(
    user_message: str, ai_response: str, context: Dict[str, Any], session: Session
) -> bool:
    """Request a memory synthesis update from the faster Gemini model."""
    if client is None:
        raise HTTPException(
            status_code=500,
            detail="Gemini client not configured; missing GEMINI_API_KEY",
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

    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text=synthesis_prompt)])
    ]

    config = types.GenerateContentConfig(
        temperature=0.3,
        system_instruction=base_profile_text,
    )

    # Rate limiting for memory synthesis
    estimated_tokens = estimate_tokens(synthesis_prompt, base_profile_text)
    await rate_limiter.wait_for_request(ALT_MODEL_NAME, estimated_tokens)

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=ALT_MODEL_NAME,
            contents=contents,
            config=config,
        )
    except Exception as exc:  # pragma: no cover
        print(f"Error updating LTM: {exc}")
        return False

    new_profile = response.text if hasattr(response, "text") and response.text else ""

    # Record token usage for memory synthesis
    memory_tokens = estimate_tokens(new_profile)
    await rate_limiter.record_usage(ALT_MODEL_NAME, memory_tokens)

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
) -> str:
    if base_prompt is None:
        base_prompt, _ = _load_base_prompt()

    timestamp_source = generated_at or local_now()

    recent_conversations = context.get("recent_conversations") or []
    recent_block = ""
    if recent_conversations:
        excerpts = []
        for entry in recent_conversations[-5:]:
            timestamp = entry.get("timestamp") or "Recent"
            user_text = (entry.get("user") or "").strip()
            catalyst_text = (entry.get("catalyst") or "").strip()

            if len(user_text) > 160:
                user_text = user_text[:157] + "…"
            if len(catalyst_text) > 200:
                catalyst_text = catalyst_text[:197] + "…"

            excerpts.append(
                f'- {timestamp}: User → "{user_text or "…"}" | Catalyst → "{catalyst_text or "…"}"'
            )

        recent_block = (
            "### Recent Conversation Highlights:\n" + "\n".join(excerpts) + "\n\n"
        )

    prompt = f"{base_prompt}\n\n" + (
        "## Current Context\n\n"
        f"### User's Goal Hierarchy:\n{json.dumps(context['goals'], indent=2)}\n\n"
        f"### User's Long-Term Memory Profile:\n{context['ltm_profile']['full_text']}\n\n"
        f"### Recent Patterns Identified:\n{context['ltm_profile']['patterns']}\n\n"
        f"### Current State:\n{context['ltm_profile']['current_state']}\n\n"
        f"{recent_block}"
        f"### Session Information:\n- Session Type: {session_type.value}\n"
        f"- Current Date: {timestamp_source.strftime('%Y-%m-%d')}\n"
        f"- Missed Sessions: {context.get('missed_sessions', [])}\n\n"
        f"## Session-Specific Instructions:\n\n{get_session_instructions(session_type)}\n"
    )
    return prompt


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


def _extract_function_calls(response: Any) -> List[Tuple[str, Dict[str, Any]]]:
    calls: List[Tuple[str, Dict[str, Any]]] = []
    candidate = (
        response.candidates[0] if getattr(response, "candidates", None) else None
    )
    if not candidate or not getattr(candidate, "content", None):
        return calls

    for part in getattr(candidate.content, "parts", []) or []:
        function_call = getattr(part, "function_call", None)
        if not function_call:
            continue
        args = _normalise_args(function_call.args)
        calls.append((function_call.name, args))

    return calls


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
) -> Dict[str, Any]:  # pragma: no cover - structure from vendor
    response_text = ""

    if response.candidates and response.candidates[0].content.parts:
        for part in response.candidates[0].content.parts:
            if getattr(part, "text", None):
                response_text += part.text

    if not response_text and hasattr(response, "text"):
        response_text = response.text

    if not response_text:
        response_text = "I'm here and ready to help you achieve your goals."

    return {
        "response": response_text,
        "memory_updated": bool(executed_calls),
        "function_calls": executed_calls,
        "thinking": json.dumps(executed_calls) if SHOW_THINKING else None,
        "model": model_used,
    }
