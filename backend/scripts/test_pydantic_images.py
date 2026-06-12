from app.models.schemas import ChatRequest
import json

payload_str = """
{
    "message": "Explain this",
    "collectionId": "all-pdfs",
    "webSearchEnabled": false,
    "thinkingEnabled": false,
    "images": [
        {
            "data": "abc",
            "mimeType": "image/png"
        }
    ]
}
"""

try:
    payload = json.loads(payload_str)
    req = ChatRequest(**payload)
    print("Parsed successfully!")
    print(f"req.images: {req.images}")
    if req.images:
        print(f"req.images[0].data: {req.images[0].data}")
        print(f"req.images[0].mime_type: {req.images[0].mime_type}")
except Exception as e:
    print(f"Failed parsing: {e}")
