from __future__ import annotations

from pathlib import Path


PAGE_MARGIN = 72
BODY_FONT_SIZE = 12
TITLE_FONT_SIZE = 20
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
LINE_HEIGHT = 17

PAGES = [
    {
        "title": "Local RAG Chat Sample Notes",
        "body": (
            "CPU scheduling algorithms include FCFS, SJF, Round Robin, and Priority Scheduling.\n\n"
            "Round Robin scheduling cycles through the ready queue, giving each ready process "
            "a fair slice of CPU time before moving on to the next one.\n\n"
            "Round Robin is commonly used in time-sharing systems because it shares the CPU fairly "
            "across active processes.\n\n"
            "A time quantum is assigned to each process. If the process does not finish within the "
            "quantum, it is preempted and placed at the back of the ready queue."
        ),
    },
    {
        "title": "Local RAG Chat Sample Notes",
        "body": (
            "If the time quantum is too large, Round Robin behaves like FCFS. If it is too small, "
            "context switching overhead becomes expensive.\n\n"
            "Priority scheduling assigns CPU time to the process with the highest priority.\n\n"
            "SJF can be treated as a special case of priority scheduling because the shortest expected "
            "CPU burst is treated as the highest priority."
        ),
    },
]


def _escape_pdf_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_text(text: str, *, max_chars: int = 88) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n\n"):
        words = paragraph.split()
        current = ""
        for word in words:
            candidate = word if not current else f"{current} {word}"
            if len(candidate) > max_chars and current:
                lines.append(current)
                current = word
                continue
            current = candidate
        if current:
            lines.append(current)
        lines.append("")
    while lines and not lines[-1]:
        lines.pop()
    return lines


def _page_stream(page_spec: dict[str, str]) -> bytes:
    operations = [
        "BT",
        f"/F1 {TITLE_FONT_SIZE} Tf",
        f"{PAGE_MARGIN} {PAGE_HEIGHT - PAGE_MARGIN} Td",
        f"({_escape_pdf_text(page_spec['title'])}) Tj",
        "ET",
    ]
    y = PAGE_HEIGHT - PAGE_MARGIN - 48
    for line in _wrap_text(page_spec["body"]):
        if not line:
            y -= LINE_HEIGHT
            continue
        operations.extend(
            [
                "BT",
                f"/F1 {BODY_FONT_SIZE} Tf",
                f"{PAGE_MARGIN} {y} Td",
                f"({_escape_pdf_text(line)}) Tj",
                "ET",
            ]
        )
        y -= LINE_HEIGHT
    return ("\n".join(operations) + "\n").encode("latin-1")


def build_sample_pdf(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [4 0 R 6 0 R] /Count 2 >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]

    for index, page_spec in enumerate(PAGES):
        page_object_number = 4 + index * 2
        stream_object_number = page_object_number + 1
        stream = _page_stream(page_spec)
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {stream_object_number} 0 R >>"
            ).encode("latin-1")
        )
        objects.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream")

    pdf = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for object_number, payload in enumerate(objects, start=1):
        offsets.append(len(pdf))
        pdf.extend(f"{object_number} 0 obj\n".encode("ascii"))
        pdf.extend(payload)
        pdf.extend(b"\nendobj\n")

    xref_offset = len(pdf)
    pdf.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    pdf.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    pdf.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    output_path.write_bytes(bytes(pdf))


def main() -> None:
    script_root = Path(__file__).resolve().parents[1]
    output_path = script_root / "data" / "uploads" / "sample_os_notes.pdf"
    build_sample_pdf(output_path)
    print(f"Wrote sample PDF to {output_path}")


if __name__ == "__main__":
    main()
