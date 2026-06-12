from __future__ import annotations
import asyncio
from pathlib import Path
import shutil
from urllib.parse import quote
from uuid import uuid4
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse

from app.dependencies import get_container, get_user_id
from app.models.schemas import IngestedDocumentSummary, PreviewResponse

if TYPE_CHECKING:
    from app.services.container import ServiceContainer

router = APIRouter(prefix="/documents", tags=["documents"])
UPLOAD_CHUNK_SIZE = 1024 * 1024


def _build_overlap_summaries(document_topics: dict[str, list[str]]) -> dict[str, str]:
    overlap_summaries: dict[str, str] = {}

    for pdf_name, topics in document_topics.items():
        topic_set = set(topics)
        best_match_name: str | None = None
        best_overlap = 0

        for other_pdf_name, other_topics in document_topics.items():
            if other_pdf_name == pdf_name:
                continue

            overlap = len(topic_set & set(other_topics))
            if overlap > best_overlap:
                best_overlap = overlap
                best_match_name = other_pdf_name

        if best_match_name and best_overlap > 0:
            overlap_summaries[pdf_name] = (
                f"{best_overlap} shared topic{'s' if best_overlap != 1 else ''} with {best_match_name}"
            )

    return overlap_summaries


def _format_size_label(source_path: str) -> str:
    path = Path(source_path)
    if not path.exists():
        return "Unknown size"

    size_bytes = path.stat().st_size
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


async def _store_upload_file(upload: UploadFile, destination: Path) -> None:
    try:
        upload.file.seek(0)
        await asyncio.to_thread(_copy_upload_file, upload.file, destination)
    finally:
        await upload.close()


def _copy_upload_file(source_file, destination: Path) -> None:
    with destination.open("wb") as output_file:
        shutil.copyfileobj(source_file, output_file, length=UPLOAD_CHUNK_SIZE)


def _serialize_documents(container: ServiceContainer, *, user_id: str) -> list[IngestedDocumentSummary]:
    documents = container.document_service.list_documents(user_id=user_id)
    document_topics = container.topic_index_service.document_topic_map(user_id=user_id)
    document_topic_details = container.topic_index_service.document_topic_details(user_id=user_id)
    overlap_summaries = _build_overlap_summaries(document_topics)
    return [
        IngestedDocumentSummary(
            **document,
            sizeLabel=_format_size_label(str(document["source_path"])),
            topics=document_topics.get(str(document["pdf_name"]), []),
            topicCollectionIds=[
                detail["id"]
                for detail in document_topic_details.get(str(document["pdf_name"]), [])
            ],
            sharedTopicSummary=overlap_summaries.get(str(document["pdf_name"])),
        )
        for document in documents
    ]


@router.get("", response_model=list[IngestedDocumentSummary])
def list_documents(
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> list[IngestedDocumentSummary]:
    return _serialize_documents(container, user_id=user_id)


@router.post("/upload", response_model=list[IngestedDocumentSummary], status_code=status.HTTP_202_ACCEPTED)
async def upload_documents(
    files: list[UploadFile] = File(...),
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> list[IngestedDocumentSummary]:
    if not files:
        raise HTTPException(status_code=400, detail="No PDF files were provided.")

    _ALLOWED_MIME_TYPES = {
        "application/pdf",
        "application/octet-stream",  # browser fallback when type sniffing fails
        "application/x-pdf",
    }

    validated_filenames: list[str] = []
    seen_filenames: set[str] = set()
    for upload in files:
        filename = Path(upload.filename or "").name
        if not filename or filename.lower().split(".")[-1] != "pdf":
            raise HTTPException(status_code=400, detail="Only PDF uploads are supported.")
        content_type = (upload.content_type or "").strip().lower()
        if content_type and content_type not in _ALLOWED_MIME_TYPES:
            raise HTTPException(
                status_code=415,
                detail=f"'{filename}' does not appear to be a PDF (received content-type '{upload.content_type}').",
            )
        if filename in seen_filenames:
            raise HTTPException(status_code=400, detail=f"Duplicate upload '{filename}' was provided.")
        seen_filenames.add(filename)
        validated_filenames.append(filename)

    created_document_ids: list[str] = []
    try:
        for filename, upload in zip(validated_filenames, files, strict=False):
            document_id = str(uuid4())
            stored_path = container.settings.uploads_dir / f"{document_id}-{filename}"
            try:
                await _store_upload_file(upload, stored_path)
            except OSError as error:
                stored_path.unlink(missing_ok=True)
                raise HTTPException(status_code=400, detail=f"Could not read {filename}.") from error

            try:
                container.document_service.create_pending_document(
                    document_id=document_id,
                    pdf_name=filename,
                    source_path=stored_path,
                    user_id=user_id,
                )
                created_document_ids.append(document_id)
            except ValueError as error:
                stored_path.unlink(missing_ok=True)
                raise HTTPException(status_code=409, detail=str(error)) from error

            try:
                container.ingestion_dispatcher.enqueue_ingestion(
                    document_id=document_id,
                    pdf_path=stored_path,
                    pdf_name=filename,
                    user_id=user_id,
                )
            except RuntimeError as error:
                raise HTTPException(
                    status_code=503,
                    detail=f"Could not queue indexing for {filename}.",
                ) from error
    except HTTPException:
        for created_document_id in reversed(created_document_ids):
            container.document_service.discard_document_by_id(
                created_document_id,
                user_id=user_id,
            )
        raise

    return _serialize_documents(container, user_id=user_id)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: str,
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> Response:
    existing = container.document_service.get_document_by_id(document_id, user_id=user_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Document '{document_id}' was not found.")

    try:
        container.document_service.remove_document_by_id(document_id, user_id=user_id)
        container.topic_index_service.remove_document_topics(
            document_id=document_id,
            user_id=user_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/preview", response_model=PreviewResponse)
def get_preview(
    pdf_name: str = Query(alias="pdfName"),
    page: int = Query(..., ge=1),
    chunk_index: int = Query(alias="chunkIndex", ge=0),
    document_id: str | None = Query(default=None, alias="documentId"),
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> PreviewResponse:
    try:
        html_content, total_pages = container.document_preview_service.render_preview_html(
            pdf_name=pdf_name,
            page_number=page,
            chunk_index=chunk_index,
            document_id=document_id,
            user_id=user_id,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

    file_url = f"/api/documents/file?pdfName={quote(pdf_name, safe='')}"
    if document_id:
        file_url += f"&documentId={quote(document_id, safe='')}"
    return PreviewResponse(
        pdfName=pdf_name,
        page=page,
        totalPages=total_pages,
        htmlContent=html_content,
        fileUrl=file_url,
    )


@router.get("/file")
def get_document_file(
    pdf_name: str = Query(alias="pdfName"),
    document_id: str | None = Query(default=None, alias="documentId"),
    container: ServiceContainer = Depends(get_container),
    user_id: str = Depends(get_user_id),
) -> FileResponse:
    document = (
        container.document_service.get_document_by_id(document_id, user_id=user_id)
        if document_id
        else container.document_service.get_document_by_name(pdf_name, user_id=user_id)
    )
    if not document:
        document_label = document_id or pdf_name
        raise HTTPException(status_code=404, detail=f"No ingested document matching '{document_label}' was found.")

    path = Path(str(document["source_path"]))
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"The file for '{pdf_name}' is no longer available.")

    return FileResponse(path, media_type="application/pdf", filename=pdf_name)
