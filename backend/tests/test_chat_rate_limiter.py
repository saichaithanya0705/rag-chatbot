from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.routers.chat import CHAT_RATE_LIMIT_DETAIL, _client_rate_limit_id, _enforce_chat_rate_limit
from app.services.chat_rate_limiter import ChatRateLimiter


class ManualClock:
    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _request(headers: dict[str, str] | None = None, client_host: str = "198.51.100.10"):
    return SimpleNamespace(
        headers=headers or {},
        client=SimpleNamespace(host=client_host),
    )


def test_rate_limiter_blocks_after_conservative_minute_budget() -> None:
    clock = ManualClock()
    limiter = ChatRateLimiter(per_minute=2, per_hour=10, clock=clock)

    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed
    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed

    blocked = limiter.check_and_record(user_id="user-a", client_id="203.0.113.10")

    assert not blocked.allowed
    assert blocked.retry_after_seconds == 60


def test_rate_limiter_reopens_window_after_old_events_expire() -> None:
    clock = ManualClock()
    limiter = ChatRateLimiter(per_minute=1, per_hour=10, clock=clock)

    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed
    assert not limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed

    clock.advance(60)

    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed


def test_rate_limiter_enforces_client_budget_across_changed_users() -> None:
    clock = ManualClock()
    limiter = ChatRateLimiter(per_minute=2, per_hour=10, clock=clock)

    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed
    assert limiter.check_and_record(user_id="user-b", client_id="203.0.113.10").allowed

    blocked = limiter.check_and_record(user_id="user-c", client_id="203.0.113.10")

    assert not blocked.allowed
    assert blocked.retry_after_seconds == 60


def test_rate_limiter_enforces_user_budget_across_changed_clients() -> None:
    clock = ManualClock()
    limiter = ChatRateLimiter(per_minute=2, per_hour=10, clock=clock)

    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed
    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.11").allowed

    blocked = limiter.check_and_record(user_id="user-a", client_id="203.0.113.12")

    assert not blocked.allowed
    assert blocked.retry_after_seconds == 60


def test_rate_limiter_hour_budget_has_long_retry_after() -> None:
    clock = ManualClock()
    limiter = ChatRateLimiter(per_minute=10, per_hour=2, clock=clock)

    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed
    assert limiter.check_and_record(user_id="user-a", client_id="203.0.113.10").allowed

    blocked = limiter.check_and_record(user_id="user-a", client_id="203.0.113.10")

    assert not blocked.allowed
    assert blocked.retry_after_seconds == 3600


def test_client_rate_limit_id_prefers_forwarded_client_ip() -> None:
    request = _request(
        headers={"x-forwarded-for": "203.0.113.20, 10.0.0.4"},
        client_host="10.0.0.5",
    )

    assert _client_rate_limit_id(request) == "203.0.113.20"


def test_chat_route_rate_limit_raises_429_with_retry_after() -> None:
    clock = ManualClock()
    limiter = ChatRateLimiter(per_minute=1, per_hour=10, clock=clock)
    container = SimpleNamespace(chat_rate_limiter=limiter)
    request = _request(headers={"x-forwarded-for": "203.0.113.20"})

    _enforce_chat_rate_limit(container=container, request=request, user_id="user-a")

    with pytest.raises(HTTPException) as raised:
        _enforce_chat_rate_limit(container=container, request=request, user_id="user-a")

    assert raised.value.status_code == 429
    assert raised.value.detail == CHAT_RATE_LIMIT_DETAIL
    assert raised.value.headers == {"Retry-After": "60"}
