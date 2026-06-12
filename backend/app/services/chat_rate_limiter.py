from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass
from math import ceil
from threading import Lock
from time import monotonic

MINUTE_WINDOW_SECONDS = 60
HOUR_WINDOW_SECONDS = 60 * 60


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    retry_after_seconds: int


class ChatRateLimiter:
    """Strict in-memory limiter for public demo chat turns."""

    def __init__(
        self,
        *,
        per_minute: int,
        per_hour: int,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if per_minute <= 0:
            raise ValueError("per_minute must be greater than zero.")
        if per_hour <= 0:
            raise ValueError("per_hour must be greater than zero.")

        self._per_minute = per_minute
        self._per_hour = per_hour
        self._clock = clock
        self._minute_events: dict[str, deque[float]] = defaultdict(deque)
        self._hour_events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check_and_record(self, *, user_id: str, client_id: str) -> RateLimitDecision:
        subjects = (
            self._subject_key("user", user_id),
            self._subject_key("client", client_id),
        )

        with self._lock:
            now = self._clock()
            retry_after_seconds = 0

            for subject in subjects:
                retry_after_seconds = max(
                    retry_after_seconds,
                    self._retry_after(
                        self._minute_events[subject],
                        limit=self._per_minute,
                        window_seconds=MINUTE_WINDOW_SECONDS,
                        now=now,
                    ),
                    self._retry_after(
                        self._hour_events[subject],
                        limit=self._per_hour,
                        window_seconds=HOUR_WINDOW_SECONDS,
                        now=now,
                    ),
                )

            if retry_after_seconds > 0:
                return RateLimitDecision(
                    allowed=False,
                    retry_after_seconds=retry_after_seconds,
                )

            for subject in subjects:
                self._minute_events[subject].append(now)
                self._hour_events[subject].append(now)

            return RateLimitDecision(allowed=True, retry_after_seconds=0)

    @staticmethod
    def _subject_key(kind: str, value: str) -> str:
        normalized = " ".join(value.strip().split())
        return f"{kind}:{normalized or 'unknown'}"

    @staticmethod
    def _retry_after(
        events: deque[float],
        *,
        limit: int,
        window_seconds: int,
        now: float,
    ) -> int:
        ChatRateLimiter._prune(events, window_seconds=window_seconds, now=now)
        if len(events) < limit:
            return 0

        oldest_event = events[0]
        return max(1, ceil(oldest_event + window_seconds - now))

    @staticmethod
    def _prune(events: deque[float], *, window_seconds: int, now: float) -> None:
        cutoff = now - window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
