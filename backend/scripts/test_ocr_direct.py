from docling.document_converter import DocumentConverter
from pathlib import Path
import sys

def test_ocr():
    image_path = Path("d:/projects/chat/test_image.png")
    if not image_path.exists():
        print(f"Error: image not found at {image_path}")
        return

    print("Initializing DocumentConverter...")
    try:
        converter = DocumentConverter()
        print("Converting image...")
        result = converter.convert(str(image_path))
        markdown_text = result.document.export_to_markdown()
        print("\n=== EXTRACTED TEXT ===")
        print(markdown_text)
        print("======================")
    except Exception as e:
        print(f"Failed: {e}")

if __name__ == "__main__":
    test_ocr()
