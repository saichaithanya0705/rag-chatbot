from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.dependencies import get_container, resolve_container_state


def _request_with_state(*, container=None, startup_error=None):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                container=container,
                container_startup_error=startup_error,
            )
        )
    )


def test_resolve_container_state_returns_container_and_error_slots() -> None:
    container = object()
    request = _request_with_state(container=container, startup_error=None)

    resolved_container, startup_error = resolve_container_state(request)  # type: ignore[arg-type]

    assert resolved_container is container
    assert startup_error is None


def test_get_container_raises_503_when_startup_failed() -> None:
    request = _request_with_state(startup_error=RuntimeError("boom"))

    with pytest.raises(HTTPException) as exc_info:
        get_container(request)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "The service failed during startup. Check backend logs for details."


def test_get_container_raises_503_while_service_is_still_starting() -> None:
    request = _request_with_state()

    with pytest.raises(HTTPException) as exc_info:
        get_container(request)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "The service is still starting up. Try again shortly."
