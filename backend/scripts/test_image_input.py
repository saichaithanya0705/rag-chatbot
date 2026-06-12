import base64
import requests
import json
from pathlib import Path

def test_image_query():
    image_path = Path("d:/projects/chat/test_image.png")
    if not image_path.exists():
        print(f"Error: image not found at {image_path}")
        return

    print("Reading and encoding image...")
    with open(image_path, "rb") as image_file:
        base64_data = base64.b64encode(image_file.read()).decode("utf-8")

    payload = {
        "message": "Explain what is described in this RAG flowchart diagram, and list out the main components shown.",
        "collectionId": "all-pdfs",
        "webSearchEnabled": False,
        "thinkingEnabled": False,
        "images": [
            {
                "data": base64_data,
                "mimeType": "image/png"
            }
        ]
    }

    headers = {
        "Content-Type": "application/json",
        "x-user-id": "dev-user"
    }

    url = "http://127.0.0.1:8000/api/chat/query"
    print(f"Sending POST request to {url}...")

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=120)
        print(f"Status Code: {response.status_code}")

        if response.status_code == 200:
            res_data = response.json()
            print("\n=== RESPONSE ANSWER ===")
            print(res_data.get("answer"))
            print("=======================")

            # Print citations if any
            citations = res_data.get("citations", [])
            if citations:
                print(f"\nCitations found: {len(citations)}")
                for i, cit in enumerate(citations):
                    print(f"  [{i+1}] {cit.get('pdfName')} (Page {cit.get('pageNumber')})")
        else:
            print("Error response text:")
            print(response.text)

    except Exception as e:
        print(f"HTTP request failed: {e}")

if __name__ == "__main__":
    test_image_query()
