from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.schemas import ChatRequest


def test_chat_request_accepts_image_only_payload() -> None:
    request = ChatRequest(
        message="   ",
        images=[{"data": "abc123", "mimeType": "image/png"}],
    )

    assert request.message == "   "
    assert len(request.images) == 1


def test_chat_request_rejects_empty_message_without_images() -> None:
    with pytest.raises(ValidationError, match="Provide a message or at least one image."):
        ChatRequest(message="   ", images=[])
