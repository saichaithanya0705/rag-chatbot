from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class HealthResponse(BaseModel):
    status: str
    nvidia_base_url: str = Field(alias="nvidiaBaseUrl")
    embed_model: str
    embedding_dimensions: int = Field(alias="embeddingDimensions")
    chat_model: str
    collection_name: str
    indexed_chunks: int
    ingestion_mode: str = Field(alias="ingestionMode")
    parser_available: bool = Field(alias="parserAvailable")
    ocr_enabled: bool = Field(alias="ocrEnabled")
    ocr_available: bool = Field(alias="ocrAvailable")
    thinking_supported: bool = Field(default=False, alias="thinkingSupported")

    model_config = {
        "populate_by_name": True,
    }


class IngestedDocumentSummary(BaseModel):
    id: str
    pdf_name: str
    size_label: str = Field(alias="sizeLabel")
    page_count: int
    chunk_count: int
    status: str
    progress: int
    error_message: str | None = Field(default=None, alias="errorMessage")
    created_at: str
    updated_at: str = Field(alias="updatedAt")
    topics: list[str] = Field(default_factory=list)
    topic_collection_ids: list[str] = Field(default_factory=list, alias="topicCollectionIds")
    shared_topic_summary: str | None = Field(default=None, alias="sharedTopicSummary")

    model_config = {
        "populate_by_name": True,
    }


class CitationPayload(BaseModel):
    id: str
    kind: str = "pdf"
    document_id: str | None = Field(default=None, alias="documentId")
    pdf_name: str | None = Field(default=None, alias="pdfName")
    page: int | None = None
    chunk_index: int | None = Field(default=None, alias="chunkIndex")
    excerpt: str
    parser: str | None = None
    source_text: str | None = Field(default=None, alias="sourceText")
    source_labels: list[str] = Field(default_factory=list, alias="sourceLabels")
    source_refs: list[str] = Field(default_factory=list, alias="sourceRefs")
    source_blocks: list[dict[str, Any]] = Field(default_factory=list, alias="sourceBlocks")
    source_location: str | None = Field(default=None, alias="sourceLocation")
    has_table: bool = Field(default=False, alias="hasTable")
    url: str | None = None
    title: str | None = None

    model_config = {
        "populate_by_name": True,
    }


class ToolCallPayload(BaseModel):
    label: str
    query: str


class AnswerTraceStepPayload(BaseModel):
    kind: str
    label: str
    detail: str


class ChatImage(BaseModel):
    data: str
    mime_type: str = Field(alias="mimeType")

    model_config = {
        "populate_by_name": True,
    }


class ChatRequest(BaseModel):
    message: str
    collection_id: str = Field(default="all-pdfs", alias="collectionId")
    session_id: str | None = Field(default=None, alias="sessionId")
    web_search_enabled: bool = Field(default=True, alias="webSearchEnabled")
    thinking_enabled: bool = Field(default=False, alias="thinkingEnabled")
    response_length: Literal["standard", "comprehensive"] = Field(default="standard", alias="responseLength")
    images: list[ChatImage] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }

    @model_validator(mode="after")
    def validate_content(self) -> "ChatRequest":
        if not self.message.strip() and not self.images:
            raise ValueError("Provide a message or at least one image.")
        return self


class ReadinessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationPayload]
    answer_trace: list[AnswerTraceStepPayload] = Field(default_factory=list, alias="answerTrace")
    collection_id: str = Field(default="all-pdfs", alias="collectionId")
    collection_label: str = Field(default="All PDFs", alias="collectionLabel")
    tool_call: ToolCallPayload | None = Field(default=None, alias="toolCall")
    web_search_requested: bool = Field(default=True, alias="webSearchRequested")
    web_search_used: bool = Field(default=False, alias="webSearchUsed")
    offline_warning: str | None = Field(default=None, alias="offlineWarning")
    cross_session_memory_used: int = Field(default=0, alias="crossSessionMemoryUsed")
    model_thinking: str | None = Field(default=None, alias="modelThinking")
    thinking_requested: bool = Field(default=False, alias="thinkingRequested")
    session_warning: str | None = Field(default=None, alias="sessionWarning")
    session_title: str | None = Field(default=None, alias="sessionTitle")

    model_config = {
        "populate_by_name": True,
    }


class SessionSummaryPayload(BaseModel):
    id: str
    title: str
    group: str
    collection_id: str = Field(alias="collectionId")
    updated_at: str = Field(alias="updatedAt")

    model_config = {
        "populate_by_name": True,
    }


class SessionMessagePayload(BaseModel):
    id: str
    role: str
    content: str
    citations: list[CitationPayload]
    answer_trace: list[AnswerTraceStepPayload] = Field(default_factory=list, alias="answerTrace")
    collection_id: str = Field(default="all-pdfs", alias="collectionId")
    collection_label: str = Field(default="All PDFs", alias="collectionLabel")
    tool_call: ToolCallPayload | None = Field(default=None, alias="toolCall")
    web_search_requested: bool = Field(default=True, alias="webSearchRequested")
    web_search_used: bool = Field(default=False, alias="webSearchUsed")
    offline_warning: str | None = Field(default=None, alias="offlineWarning")
    cross_session_memory_used: int = Field(default=0, alias="crossSessionMemoryUsed")
    model_thinking: str | None = Field(default=None, alias="modelThinking")
    thinking_requested: bool = Field(default=False, alias="thinkingRequested")
    created_at: str = Field(alias="createdAt")

    model_config = {
        "populate_by_name": True,
    }


class SessionDetailResponse(SessionSummaryPayload):
    messages: list[SessionMessagePayload]


class CreateSessionRequest(BaseModel):
    collection_id: str = Field(default="all-pdfs", alias="collectionId")

    model_config = {
        "populate_by_name": True,
    }


class PreviewResponse(BaseModel):
    pdf_name: str = Field(alias="pdfName")
    page: int
    total_pages: int = Field(alias="totalPages")
    html_content: str = Field(alias="htmlContent")
    file_url: str | None = Field(default=None, alias="fileUrl")

    model_config = {
        "populate_by_name": True,
    }


class TopicSummaryPayload(BaseModel):
    id: str
    label: str
    chunk_count: int = Field(alias="chunkCount")
    document_count: int = Field(alias="documentCount")

    model_config = {
        "populate_by_name": True,
    }


class ReclusterResponse(BaseModel):
    topics: list[TopicSummaryPayload]
    indexed_chunks: int = Field(alias="indexedChunks")
    document_count: int = Field(alias="documentCount")

    model_config = {
        "populate_by_name": True,
    }


class GraphNodePayload(BaseModel):
    id: str
    label: str
    chunk_count: int = Field(alias="chunkCount")
    document_count: int = Field(alias="documentCount")
    keywords: list[str] = Field(default_factory=list)
    source_documents: list[str] = Field(default_factory=list, alias="sourceDocuments")
    page_keys: list[str] = Field(default_factory=list, alias="pageKeys")

    model_config = {
        "populate_by_name": True,
    }


class GraphEdgePayload(BaseModel):
    source: str
    target: str
    weight: float
    directed: bool = True
    semantic_score: float = Field(default=0.0, alias="semanticScore")
    page_overlap_score: float = Field(default=0.0, alias="pageOverlapScore")
    document_overlap_score: float = Field(default=0.0, alias="documentOverlapScore")
    shared_pages: list[str] = Field(default_factory=list, alias="sharedPages")
    shared_documents: list[str] = Field(default_factory=list, alias="sharedDocuments")
    reason: str = "Related by the knowledge graph scoring model."

    model_config = {
        "populate_by_name": True,
    }


class GraphResponse(BaseModel):
    nodes: list[GraphNodePayload]
    edges: list[GraphEdgePayload]


class AnalyticsTopicPayload(BaseModel):
    label: str
    chunk_count: int = Field(alias="chunkCount")

    model_config = {
        "populate_by_name": True,
    }


class AnalyticsSummaryResponse(BaseModel):
    total_documents: int = Field(alias="totalDocuments")
    total_chunks: int = Field(alias="totalChunks")
    total_topics: int = Field(alias="totalTopics")
    avg_chunks_per_doc: float = Field(alias="avgChunksPerDoc")
    top_topics: list[AnalyticsTopicPayload] = Field(alias="topTopics")
    storage_used_bytes: int = Field(alias="storageUsedBytes")

    model_config = {
        "populate_by_name": True,
    }
