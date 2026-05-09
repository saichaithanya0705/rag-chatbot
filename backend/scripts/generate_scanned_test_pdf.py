from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


PAGE_SIZE = (1654, 2339)
TEXT_POSITION = (140, 220)
FONT_SIZE = 44
TEXT_LINES = [
    "Round robin scheduling uses a fixed time quantum and preemption.",
    "Context switching overhead increases when the quantum becomes too small.",
]


def _load_font() -> ImageFont.ImageFont:
    windows_font = Path("C:/Windows/Fonts/arial.ttf")
    if windows_font.exists():
        return ImageFont.truetype(str(windows_font), FONT_SIZE)
    return ImageFont.load_default()


def _build_page(text: str, font: ImageFont.ImageFont) -> Image.Image:
    image = Image.new("RGB", PAGE_SIZE, "white")
    draw = ImageDraw.Draw(image)
    draw.multiline_text(TEXT_POSITION, text, fill="black", font=font, spacing=16)
    return image


def main() -> None:
    output_path = Path(__file__).resolve().parents[1] / "data" / "uploads" / "ocr_phase6_scan.pdf"
    font = _load_font()
    pages = [_build_page(text, font) for text in TEXT_LINES]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pages[0].save(output_path, save_all=True, append_images=pages[1:])
    print(output_path)


if __name__ == "__main__":
    main()
