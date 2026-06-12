from __future__ import annotations

from collections.abc import Mapping, Sequence


DOCUMENT_INVENTORY_DISPLAY_LIMIT = 20


def build_document_inventory_answer(documents: Sequence[Mapping[str, object]]) -> str:
    if not documents:
        return (
            "I do not currently have any PDFs indexed for this workspace. "
            "Upload a PDF in the pipeline view, then ask again."
        )

    indexed_count = sum(1 for document in documents if str(document.get("status", "")).lower() == "indexed")
    total_count = len(documents)
    if indexed_count:
        header = (
            f"I can access {indexed_count} indexed PDF"
            f"{'' if indexed_count == 1 else 's'} in this workspace"
        )
        if indexed_count != total_count:
            header += f" ({total_count} total PDF records)"
        header += "."
    else:
        header = (
            f"I can see {total_count} PDF record{'' if total_count == 1 else 's'} in this workspace, "
            "but none are indexed for grounded answers yet."
        )

    visible_documents = documents[:DOCUMENT_INVENTORY_DISPLAY_LIMIT]
    lines = [_format_document_inventory_line(document) for document in visible_documents]
    if len(documents) > DOCUMENT_INVENTORY_DISPLAY_LIMIT:
        remaining_count = len(documents) - DOCUMENT_INVENTORY_DISPLAY_LIMIT
        lines.append(f"- ...and {remaining_count} more.")

    return f"{header}\n\n" + "\n".join(lines)


def _format_document_inventory_line(document: Mapping[str, object]) -> str:
    name = str(document.get("pdf_name") or "Unnamed PDF")
    status = str(document.get("status") or "unknown").lower()
    page_count = _document_int(document, "page_count")
    chunk_count = _document_int(document, "chunk_count")
    progress = _document_int(document, "progress")

    if status == "indexed":
        return (
            f"- {name} - indexed; "
            f"{_pluralize(page_count, 'page')}; {_pluralize(chunk_count, 'chunk')}."
        )

    if status == "error":
        error_message = str(document.get("error_message") or "indexing failed")
        return f"- {name} - error: {error_message}."

    status_label = status.replace("_", " ")
    return f"- {name} - {status_label} ({progress}%); not ready for grounded answers yet."


def _document_int(document: Mapping[str, object], key: str) -> int:
    try:
        return int(document.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _pluralize(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"
