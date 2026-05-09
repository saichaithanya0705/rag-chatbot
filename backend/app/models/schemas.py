from __future__ import annotations

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str
    ollama_base_url: str
    embed_model: str
    chat_model: str
    collection_name: str
    indexed_chunks: int
    ingestion_mode: str = Field(alias="ingestionMode")
    ocr_enabled: bool = Field(alias="ocrEnabled")
    ocr_available: bool = Field(alias="ocrAvailable")

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


class ChatRequest(BaseModel):
    message: str
    collection_id: str = Field(default="all-pdfs", alias="collectionId")
    session_id: str | None = Field(default=None, alias="sessionId")
    web_search_enabled: bool = Field(default=True, alias="webSearchEnabled")
    thinking_enabled: bool = Field(default=False, alias="thinkingEnabled")

    model_config = {
        "populate_by_name": True,
    }


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

    model_config = {
        "populate_by_name": True,
    }


class GraphEdgePayload(BaseModel):
    source: str
    target: str
    weight: float
    directed: bool = True


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
