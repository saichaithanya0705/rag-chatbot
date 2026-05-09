from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class Database:
    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 5000")
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    title TEXT,
                    collection TEXT,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    collection_id TEXT NOT NULL DEFAULT 'all-pdfs',
                    collection_label TEXT NOT NULL DEFAULT 'All PDFs',
                    citations TEXT,
                    answer_trace TEXT,
                    tool_call TEXT,
                    web_search_requested INTEGER NOT NULL DEFAULT 1,
                    web_search_used INTEGER NOT NULL DEFAULT 0,
                    offline_warning TEXT,
                    thinking_requested INTEGER NOT NULL DEFAULT 0,
                    cross_session_memory_used INTEGER NOT NULL DEFAULT 0,
                    embedding_id TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ingested_documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    pdf_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'indexed',
                    progress INTEGER NOT NULL DEFAULT 100,
                    error_message TEXT,
                    chunking_threshold REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ingested_pages (
                    document_id TEXT NOT NULL REFERENCES ingested_documents(id) ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY (document_id, page_number)
                );

                CREATE TABLE IF NOT EXISTS topic_overrides (
                    cluster_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS retrieval_corpus_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    version INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS retrieval_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    pdf_name TEXT NOT NULL,
                    page_number INTEGER NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    collection_id TEXT,
                    is_indexed INTEGER NOT NULL DEFAULT 0,
                    text TEXT NOT NULL
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS retrieval_chunks_fts
                USING fts5(
                    text,
                    content='retrieval_chunks',
                    content_rowid='rowid',
                    tokenize='unicode61 remove_diacritics 2'
                );
                """
            )
            connection.execute(
                """
                INSERT INTO retrieval_corpus_state (id, version)
                VALUES (1, 0)
                ON CONFLICT(id) DO NOTHING
                """
            )
            connection.executescript(
                """
                CREATE TRIGGER IF NOT EXISTS retrieval_chunks_ai
                AFTER INSERT ON retrieval_chunks
                BEGIN
                    INSERT INTO retrieval_chunks_fts(rowid, text)
                    VALUES (new.rowid, new.text);
                END;

                CREATE TRIGGER IF NOT EXISTS retrieval_chunks_ad
                AFTER DELETE ON retrieval_chunks
                BEGIN
                    INSERT INTO retrieval_chunks_fts(retrieval_chunks_fts, rowid, text)
                    VALUES ('delete', old.rowid, old.text);
                END;

                CREATE TRIGGER IF NOT EXISTS retrieval_chunks_au
                AFTER UPDATE ON retrieval_chunks
                BEGIN
                    INSERT INTO retrieval_chunks_fts(retrieval_chunks_fts, rowid, text)
                    VALUES ('delete', old.rowid, old.text);
                    INSERT INTO retrieval_chunks_fts(rowid, text)
                    VALUES (new.rowid, new.text);
                END;
                """
            )
            self._ensure_retrieval_fts_index(connection)
            self._ensure_column(connection, "messages", "tool_call", "TEXT")
            self._ensure_column(connection, "messages", "model_thinking", "TEXT")
            self._ensure_column(
                connection,
                "messages",
                "thinking_requested",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(
                connection,
                "messages",
                "collection_id",
                "TEXT NOT NULL DEFAULT 'all-pdfs'",
            )
            self._ensure_column(
                connection,
                "messages",
                "collection_label",
                "TEXT NOT NULL DEFAULT 'All PDFs'",
            )
            self._ensure_column(connection, "messages", "answer_trace", "TEXT")
            self._ensure_column(
                connection,
                "messages",
                "web_search_requested",
                "INTEGER NOT NULL DEFAULT 1",
            )
            self._ensure_column(
                connection,
                "messages",
                "web_search_used",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(connection, "messages", "offline_warning", "TEXT")
            self._ensure_column(
                connection,
                "messages",
                "cross_session_memory_used",
                "INTEGER NOT NULL DEFAULT 0",
            )
            self._ensure_column(connection, "sessions", "user_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_column(connection, "messages", "user_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_column(connection, "ingested_documents", "status", "TEXT NOT NULL DEFAULT 'indexed'")
            self._ensure_column(connection, "ingested_documents", "progress", "INTEGER NOT NULL DEFAULT 100")
            self._ensure_column(connection, "ingested_documents", "error_message", "TEXT")
            self._ensure_column(connection, "ingested_documents", "chunking_threshold", "REAL")
            self._ensure_column(connection, "ingested_documents", "updated_at", "TEXT")
            self._ensure_column(connection, "ingested_documents", "user_id", "TEXT NOT NULL DEFAULT 'default'")
            self._ensure_document_table_user_scope(connection)
            connection.execute(
                """
                UPDATE ingested_documents
                SET updated_at = COALESCE(updated_at, created_at),
                    status = COALESCE(status, 'indexed'),
                    progress = COALESCE(progress, 100),
                    user_id = COALESCE(user_id, 'default')
                """
            )
            connection.execute(
                """
                UPDATE messages
                SET collection_id = COALESCE(
                        collection_id,
                        (SELECT collection FROM sessions WHERE sessions.id = messages.session_id),
                        'all-pdfs'
                    ),
                    collection_label = COALESCE(
                        collection_label,
                        CASE
                            WHEN COALESCE(
                                collection_id,
                                (SELECT collection FROM sessions WHERE sessions.id = messages.session_id),
                                'all-pdfs'
                            ) = 'all-pdfs'
                                THEN 'All PDFs'
                            ELSE COALESCE(
                                collection_id,
                                (SELECT collection FROM sessions WHERE sessions.id = messages.session_id),
                                'all-pdfs'
                            )
                        END
                    ),
                    web_search_requested = COALESCE(web_search_requested, 1),
                    thinking_requested = COALESCE(thinking_requested, 0)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_messages_session_user_created_at_id
                ON messages(session_id, user_id, created_at, id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingested_documents_user_status
                ON ingested_documents(user_id, status)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ingested_documents_user_updated_at
                ON ingested_documents(user_id, updated_at DESC, created_at DESC)
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_ingested_documents_user_pdf_name
                ON ingested_documents(user_id, pdf_name)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_scope
                ON retrieval_chunks(user_id, is_indexed, collection_id)
                """
            )
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_retrieval_chunks_document
                ON retrieval_chunks(document_id, user_id)
                """
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table_name: str,
        column_name: str,
        column_definition: str,
    ) -> None:
        existing_columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return

        connection.execute(
            f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}"
        )

    @staticmethod
    def _ensure_document_table_user_scope(connection: sqlite3.Connection) -> None:
        indexes = connection.execute("PRAGMA index_list(ingested_documents)").fetchall()
        has_user_pdf_index = any(str(row["name"]) == "idx_ingested_documents_user_pdf_name" for row in indexes)
        if has_user_pdf_index:
            return

        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.executescript(
                """
                ALTER TABLE ingested_pages RENAME TO ingested_pages_legacy;
                ALTER TABLE ingested_documents RENAME TO ingested_documents_legacy;

                CREATE TABLE ingested_documents (
                    id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL DEFAULT 'default',
                    pdf_name TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    page_count INTEGER NOT NULL,
                    chunk_count INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'indexed',
                    progress INTEGER NOT NULL DEFAULT 100,
                    error_message TEXT,
                    chunking_threshold REAL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                CREATE TABLE ingested_pages (
                    document_id TEXT NOT NULL REFERENCES ingested_documents(id) ON DELETE CASCADE,
                    page_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    PRIMARY KEY (document_id, page_number)
                );

                INSERT INTO ingested_documents (
                    id,
                    user_id,
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    status,
                    progress,
                    error_message,
                    chunking_threshold,
                    created_at,
                    updated_at
                )
                SELECT
                    id,
                    COALESCE(user_id, 'default'),
                    pdf_name,
                    source_path,
                    page_count,
                    chunk_count,
                    COALESCE(status, 'indexed'),
                    COALESCE(progress, 100),
                    error_message,
                    chunking_threshold,
                    created_at,
                    COALESCE(updated_at, created_at)
                FROM ingested_documents_legacy;

                INSERT INTO ingested_pages (document_id, page_number, content)
                SELECT document_id, page_number, content
                FROM ingested_pages_legacy;

                DROP TABLE ingested_pages_legacy;
                DROP TABLE ingested_documents_legacy;
                """
            )
        finally:
            connection.execute("PRAGMA foreign_keys = ON")

    @staticmethod
    def _ensure_retrieval_fts_index(connection: sqlite3.Connection) -> None:
        retrieval_row = connection.execute(
            "SELECT COUNT(*) AS total FROM retrieval_chunks"
        ).fetchone()
        fts_row = connection.execute(
            "SELECT COUNT(*) AS total FROM retrieval_chunks_fts"
        ).fetchone()
        retrieval_count = int(retrieval_row["total"]) if retrieval_row else 0
        fts_count = int(fts_row["total"]) if fts_row else 0
        if retrieval_count == fts_count:
            return

        connection.execute(
            "INSERT INTO retrieval_chunks_fts(retrieval_chunks_fts) VALUES ('rebuild')"
        )
