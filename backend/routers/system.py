"""System, health, and utility API routes."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models
from ..catalyst_ai import (
    _extract_response_text,
    _make_api_call_with_retry,
    get_session_instructions,
)
from ..config import MODEL_NAME
from ..dependencies import get_db
from ..llm_client import is_configured
from ..rate_limiter import estimate_tokens, rate_limiter
from ..schemas import SessionType

router = APIRouter()


@router.get("/")
async def root() -> Dict[str, Any]:
    return {
        "status": "active",
        "message": "The Catalyst is ready",
        "version": "2.0",
        "model": MODEL_NAME,
    }


@router.get("/health")
async def health_check(db: Session = Depends(get_db)) -> Dict[str, Any]:
    try:
        goal_count = db.query(models.Goal).count()
        memory_count = db.query(models.LTMProfile).count()
        return {
            "status": "healthy",
            "version": "2.0",
            "database": "connected",
            "goals_count": goal_count,
            "memory_profiles": memory_count,
            "function_calling": "structured_json",
            "ai_model": MODEL_NAME,
            "rate_limits": {
                model: limits for model, limits in rate_limiter._limits.items()
            },
        }
    except Exception as exc:  # pragma: no cover
        return {"status": "unhealthy", "error": str(exc), "version": "2.0"}


@router.get("/test/functions")
async def test_function_calling() -> Dict[str, Any]:
    if not is_configured():
        raise HTTPException(status_code=500, detail="CLOD API key not configured")

    try:
        test_message = (
            'Respond with JSON: {"reply": "Test ok", "daily_log": null, '
            '"memory_update": null, "insights": null}'
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a test assistant. Respond with valid JSON only."
                ),
            },
            {"role": "user", "content": test_message},
        ]

        estimated = estimate_tokens(test_message)
        response, model_used = await _make_api_call_with_retry(
            MODEL_NAME,
            messages,
            temperature=0.3,
            estimated_prompt_tokens=estimated,
            context="test",
        )
        response_text = _extract_response_text(response)
        await rate_limiter.record_usage(model_used, estimate_tokens(response_text))

        return {
            "status": "success",
            "transport": "structured_json",
            "test_response": {
                "text_response": response_text,
                "has_json": response_text.strip().startswith("{"),
            },
        }
    except Exception as exc:  # pragma: no cover
        return {"status": "error", "error": str(exc), "error_type": type(exc).__name__}


@router.get("/session/instructions/{session_type}")
async def session_instructions(session_type: SessionType) -> Dict[str, Any]:
    return {
        "session_type": session_type.value,
        "instructions": get_session_instructions(session_type),
    }


@router.get("/rate-limit-status")
async def get_rate_limit_status() -> Dict[str, Any]:
    """Provide current rate limit status for frontend awareness."""
    import time

    status = {}
    current_time = time.monotonic()

    for model_name, limits in rate_limiter._limits.items():
        if model_name not in rate_limiter._states:
            status[model_name] = {
                "requests_remaining": limits.get("rpm", 0),
                "tokens_remaining": limits.get("tpm", 0),
                "daily_requests_remaining": limits.get("rpd", 0),
                "estimated_wait_seconds": 0,
                "quota_status": "available",
            }
            continue

        state = rate_limiter._states[model_name]

        requests_used_this_minute = len(
            [t for t in state.minute_requests if current_time - t < 60.0]
        )

        tokens_used_this_minute = sum(
            [
                count
                for timestamp, count in state.token_events
                if current_time - timestamp < 60.0
            ]
        )

        requests_used_today = len(
            [t for t in state.day_requests if current_time - t < 86400.0]
        )

        rpm_limit = limits.get("rpm", 0)
        tpm_limit = limits.get("tpm", 0)
        rpd_limit = limits.get("rpd", 0)

        requests_remaining = (
            max(0, rpm_limit - requests_used_this_minute) if rpm_limit else float("inf")
        )
        tokens_remaining = (
            max(0, tpm_limit - tokens_used_this_minute) if tpm_limit else float("inf")
        )
        daily_remaining = (
            max(0, rpd_limit - requests_used_today) if rpd_limit else float("inf")
        )

        estimated_wait = 0
        if requests_remaining == 0 and state.minute_requests:
            estimated_wait = max(
                estimated_wait, 60.0 - (current_time - state.minute_requests[0])
            )
        if tokens_remaining == 0 and state.token_events:
            estimated_wait = max(
                estimated_wait, 60.0 - (current_time - state.token_events[0][0])
            )
        if daily_remaining == 0 and state.day_requests:
            estimated_wait = max(
                estimated_wait, 86400.0 - (current_time - state.day_requests[0])
            )

        if estimated_wait > 0:
            quota_status = "rate_limited"
        elif (requests_remaining / rpm_limit if rpm_limit else 1) < 0.2:
            quota_status = "approaching_limit"
        else:
            quota_status = "available"

        status[model_name] = {
            "requests_remaining": int(requests_remaining)
            if requests_remaining != float("inf")
            else None,
            "tokens_remaining": int(tokens_remaining)
            if tokens_remaining != float("inf")
            else None,
            "daily_requests_remaining": int(daily_remaining)
            if daily_remaining != float("inf")
            else None,
            "estimated_wait_seconds": max(0, int(estimated_wait)),
            "quota_status": quota_status,
            "limits": {
                "rpm": rpm_limit or None,
                "tpm": tpm_limit or None,
                "rpd": rpd_limit or None,
            },
        }

    return {"models": status, "primary_model": MODEL_NAME, "timestamp": current_time}
