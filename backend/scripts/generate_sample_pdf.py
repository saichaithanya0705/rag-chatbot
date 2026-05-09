from __future__ import annotations

from pathlib import Path

import fitz


PAGE_MARGIN = 72
BODY_FONT_SIZE = 12
TITLE_FONT_SIZE = 20

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


def build_sample_pdf(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    document = fitz.open()

    for page_spec in PAGES:
        page = document.new_page()
        page_rect = page.rect
        title_rect = fitz.Rect(
            PAGE_MARGIN,
            PAGE_MARGIN - 12,
            page_rect.width - PAGE_MARGIN,
            PAGE_MARGIN + 28,
        )
        body_rect = fitz.Rect(
            PAGE_MARGIN,
            PAGE_MARGIN + 40,
            page_rect.width - PAGE_MARGIN,
            page_rect.height - PAGE_MARGIN,
        )

        page.insert_textbox(
            title_rect,
            page_spec["title"],
            fontsize=TITLE_FONT_SIZE,
            fontname="helv",
            fontfile=None,
        )
        inserted_height = page.insert_textbox(
            body_rect,
            page_spec["body"],
            fontsize=BODY_FONT_SIZE,
            fontname="helv",
            lineheight=1.45,
        )
        if inserted_height < 0:
            raise RuntimeError("Sample PDF text overflowed the page layout.")

    document.save(output_path)
    document.close()


def main() -> None:
    script_root = Path(__file__).resolve().parents[1]
    output_path = script_root / "data" / "uploads" / "sample_os_notes.pdf"
    build_sample_pdf(output_path)
    print(f"Wrote sample PDF to {output_path}")


if __name__ == "__main__":
    main()
