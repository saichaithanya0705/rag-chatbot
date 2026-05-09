from __future__ import annotations

from dataclasses import dataclass

from app.core.chroma_store import ChromaStore
from app.core.config import Settings
from app.core.database import Database
from app.services.docling_parser import DoclingDocumentParser
from app.services.document_service import DocumentService
from app.services.history_service import HistoryService
from app.services.ingestion_dispatcher import IngestionDispatcher
from app.services.ingestion_service import IngestionService
from app.services.kg_manager import KgManager
from app.services.keyword_service import KeywordService
from app.services.ollama_client import OllamaClient
from app.services.query_rewrite_service import QueryRewriteService
from app.services.rag_service import RagService
from app.services.reranker_service import RerankerService
from app.services.text_splitter import SemanticTextSplitter
from app.services.topic_index_service import TopicIndexService
from app.services.web_search_service import WebSearchService


@dataclass
class ServiceContainer:
    settings: Settings
    database: Database
    chroma_store: ChromaStore
    ollama_client: OllamaClient
    keyword_service: KeywordService
    document_service: DocumentService
    history_service: HistoryService
    kg_manager: KgManager
    topic_index_service: TopicIndexService
    document_parser: DoclingDocumentParser
    ingestion_dispatcher: IngestionDispatcher
    query_rewrite_service: QueryRewriteService
    reranker_service: RerankerService
    web_search_service: WebSearchService
    ingestion_service: IngestionService
    rag_service: RagService

    async def aclose(self) -> None:
        await self.keyword_service.aclose()
        await self.web_search_service.aclose()
        await self.ollama_client.aclose()


def build_container(settings: Settings) -> ServiceContainer:
    database = Database(settings.sqlite_path)
    database.initialize()

    chroma_store = ChromaStore(str(settings.chroma_path))
    ollama_client = OllamaClient(
        base_url=settings.ollama_base_url,
        embed_model=settings.embed_model,
        chat_model=settings.chat_model,
    )
    document_service = DocumentService(database=database, chroma_store=chroma_store)
    history_service = HistoryService(
        database=database,
        chroma_store=chroma_store,
        memory_collection_name=settings.chat_history_collection_name,
        cross_session_memory_enabled=settings.cross_session_memory_enabled,
    )
    kg_manager = KgManager(settings.kg_path)
    topic_index_service = TopicIndexService(
        chroma_store=chroma_store,
        database=database,
        kg_manager=kg_manager,
        topic_collection_prefix=settings.topic_collection_prefix,
    )
    document_parser = DoclingDocumentParser(
        ocr_enabled=settings.docling_ocr_enabled,
        table_structure_enabled=settings.docling_table_structure_enabled,
        artifacts_path=settings.docling_artifacts_dir,
    )
    ingestion_dispatcher = IngestionDispatcher(settings=settings)
    reranker_service = RerankerService(settings.reranker_model)
    web_search_service = WebSearchService(
        backend=settings.web_search_backend,
        region=settings.web_search_region,
        max_results=settings.web_search_max_results,
    )
    query_rewrite_service = QueryRewriteService(ollama_client=ollama_client)
    keyword_service = KeywordService(
        base_url=settings.ollama_base_url,
        embed_model=settings.embed_model,
        chat_model=settings.chat_model,
    )
    text_splitter = SemanticTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )
    ingestion_service = IngestionService(
        document_service=document_service,
        keyword_service=keyword_service,
        ollama_client=ollama_client,
        text_splitter=text_splitter,
        chroma_store=chroma_store,
        topic_index_service=topic_index_service,
        document_parser=document_parser,
    )
    rag_service = RagService(
        ollama_client=ollama_client,
        chroma_store=chroma_store,
        document_service=document_service,
        kg_manager=kg_manager,
        query_rewrite_service=query_rewrite_service,
        reranker_service=reranker_service,
        web_search_service=web_search_service,
        top_k=settings.top_k,
        web_search_score_threshold=settings.web_search_score_threshold,
    )

    return ServiceContainer(
        settings=settings,
        database=database,
        chroma_store=chroma_store,
        ollama_client=ollama_client,
        keyword_service=keyword_service,
        document_service=document_service,
        history_service=history_service,
        kg_manager=kg_manager,
        topic_index_service=topic_index_service,
        document_parser=document_parser,
        ingestion_dispatcher=ingestion_dispatcher,
        query_rewrite_service=query_rewrite_service,
        reranker_service=reranker_service,
        web_search_service=web_search_service,
        ingestion_service=ingestion_service,
        rag_service=rag_service,
    )
