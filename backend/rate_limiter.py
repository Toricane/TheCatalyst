"""Asynchronous rate limiter for Gemini API usage."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional

from .config import GEMINI_RATE_LIMITS

_TOKEN_WINDOW_SECONDS = 60.0
_DAY_WINDOW_SECONDS = 86_400.0


@dataclass
class _ModelState:
    minute_requests: Deque[float] = field(default_factory=deque)
    day_requests: Deque[float] = field(default_factory=deque)
    token_events: Deque[tuple[float, int]] = field(default_factory=deque)
    token_sum: int = 0
    placeholder_tokens: Deque[int] = field(default_factory=deque)
    pending_token_sum: int = 0


class RateLimiter:
    """Rate limiter that enforces per-model quotas for Gemini usage."""

    def __init__(self, limits: Dict[str, Dict[str, int]]) -> None:
        self._limits = limits
        self._states: Dict[str, _ModelState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

    def _get_state(self, model: str) -> _ModelState:
        if model not in self._states:
            self._states[model] = _ModelState()
        return self._states[model]

    def _get_lock(self, model: str) -> asyncio.Lock:
        if model not in self._locks:
            self._locks[model] = asyncio.Lock()
        return self._locks[model]

    def _prune_requests(self, state: _ModelState, now: float) -> None:
        while (
            state.minute_requests
            and now - state.minute_requests[0] >= _TOKEN_WINDOW_SECONDS
        ):
            state.minute_requests.popleft()
        while state.day_requests and now - state.day_requests[0] >= _DAY_WINDOW_SECONDS:
            state.day_requests.popleft()

    def _prune_tokens(self, state: _ModelState, now: float) -> None:
        while (
            state.token_events
            and now - state.token_events[0][0] >= _TOKEN_WINDOW_SECONDS
        ):
            _, count = state.token_events.popleft()
            state.token_sum = max(0, state.token_sum - count)

    def _compute_wait_time(
        self,
        state: _ModelState,
        now: float,
        limits: Dict[str, int],
        reserve: int,
    ) -> float:
        wait_time = 0.0

        rpm = limits.get("rpm", 0) or 0
        rpd = limits.get("rpd", 0) or 0
        tpm = limits.get("tpm", 0) or 0

        if rpm and len(state.minute_requests) >= rpm:
            wait_time = max(
                wait_time,
                state.minute_requests[0] + _TOKEN_WINDOW_SECONDS - now,
            )
        if rpd and len(state.day_requests) >= rpd:
            wait_time = max(
                wait_time, state.day_requests[0] + _DAY_WINDOW_SECONDS - now
            )
        if tpm:
            effective_tokens = state.token_sum + state.pending_token_sum + reserve
            if effective_tokens > tpm:
                if state.token_events:
                    wait_time = max(
                        wait_time,
                        state.token_events[0][0] + _TOKEN_WINDOW_SECONDS - now,
                    )
                else:
                    wait_time = max(wait_time, _TOKEN_WINDOW_SECONDS)

        return wait_time

    async def get_wait_time(
        self, model: str, estimated_prompt_tokens: int = 0
    ) -> float:
        """Return the expected wait time before a request can be made."""

        limits = self._limits.get(model)
        if not limits:
            return 0.0

        reserve = max(0, int(estimated_prompt_tokens))

        async with self._get_lock(model):
            state = self._get_state(model)
            now = time.monotonic()
            self._prune_requests(state, now)
            if limits.get("tpm"):
                self._prune_tokens(state, now)
            return self._compute_wait_time(state, now, limits, reserve)

    async def wait_for_request(
        self, model: str, estimated_prompt_tokens: int = 0
    ) -> None:
        limits = self._limits.get(model)
        if not limits:
            return

        reserve = max(0, int(estimated_prompt_tokens))

        while True:
            async with self._get_lock(model):
                state = self._get_state(model)
                now = time.monotonic()
                self._prune_requests(state, now)
                self._prune_tokens(state, now)
                wait_time = self._compute_wait_time(state, now, limits, reserve)

                if wait_time <= 0:
                    state.minute_requests.append(now)
                    state.day_requests.append(now)
                    if reserve:
                        state.placeholder_tokens.append(reserve)
                        state.pending_token_sum += reserve
                    return

            await asyncio.sleep(wait_time if wait_time > 0 else 0.05)

    async def record_usage(self, model: str, tokens_used: int) -> None:
        limits = self._limits.get(model)
        if not limits:
            return

        tokens = max(0, int(tokens_used))
        tpm = limits.get("tpm", 0) or 0

        while True:
            async with self._get_lock(model):
                state = self._get_state(model)
                now = time.monotonic()
                self._prune_tokens(state, now)

                reserved = 0
                if state.placeholder_tokens:
                    reserved = state.placeholder_tokens.popleft()
                    state.pending_token_sum = max(0, state.pending_token_sum - reserved)

                tentative_total = state.token_sum + tokens
                wait_time = 0.0
                if tpm and tentative_total > tpm:
                    if reserved:
                        state.placeholder_tokens.appendleft(reserved)
                        state.pending_token_sum += reserved
                    if state.token_events:
                        wait_time = max(
                            wait_time,
                            state.token_events[0][0] + _TOKEN_WINDOW_SECONDS - now,
                        )
                    else:
                        wait_time = max(wait_time, _TOKEN_WINDOW_SECONDS)
                    # Returning to the loop to wait before retrying
                else:
                    if tokens:
                        state.token_events.append((now, tokens))
                        state.token_sum += tokens
                    return

            await asyncio.sleep(wait_time if wait_time > 0 else 0.05)


def estimate_tokens(*segments: Optional[str]) -> int:
    """Crude token estimation using character length heuristics."""

    combined = " ".join(segment for segment in segments if segment)
    if not combined:
        return 0
    # Rough heuristic: 4 characters ~= 1 token
    estimated = max(1, len(combined) // 4)
    return estimated


rate_limiter = RateLimiter(GEMINI_RATE_LIMITS)
