from __future__ import annotations

import unittest

from app.services.document_parser import ParsedBlock
from app.services.ingestion_chunk_builder import IngestionChunkBuilder


def _block(text: str, *, page_number: int = 1) -> ParsedBlock:
    return ParsedBlock(
        text=text,
        page_number=page_number,
        label="text",
        top=0.0,
        bottom=10.0,
        page_height=800.0,
    )


class _FakeSplitter:
    async def split_text(
        self,
        text: str,
        *,
        threshold: float | None = None,
        blocks: list[str] | None = None,
    ) -> list[str]:
        if blocks is not None:
            return [" | ".join(blocks)]
        return [text.strip()]


class IngestionChunkBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_non_qa_documents_use_docling_block_text_as_splitter_context(self) -> None:
        builder = IngestionChunkBuilder(text_splitter=_FakeSplitter())

        drafts, carryover = await builder.build_page_chunk_drafts(
            page_number=1,
            page_text="Header\n\nBody",
            page_blocks=[_block("Header"), _block("Body")],
            threshold=None,
            qa_document=False,
            carryover_question=None,
        )

        self.assertIsNone(carryover)
        self.assertEqual([draft.text for draft in drafts], ["Header | Body"])
        self.assertEqual(drafts[0].metadata, {})

    async def test_qa_documents_carry_unfinished_question_to_next_page(self) -> None:
        builder = IngestionChunkBuilder(text_splitter=_FakeSplitter())
        question_blocks = [
            _block("1. What is a process state?"),
            _block("A process may be ready, running, or waiting."),
        ]

        first_page_drafts, carryover = await builder.build_page_chunk_drafts(
            page_number=3,
            page_text="\n\n".join(block.text for block in question_blocks),
            page_blocks=question_blocks,
            threshold=None,
            qa_document=True,
            carryover_question=None,
        )

        self.assertEqual(carryover, "What is a process state?")
        self.assertEqual(first_page_drafts[0].metadata["content_type"], "qa")
        self.assertEqual(first_page_drafts[0].metadata["qa_question"], "What is a process state?")

        second_page_drafts, next_carryover = await builder.build_page_chunk_drafts(
            page_number=4,
            page_text="It can transition after scheduling or I/O events.",
            page_blocks=[_block("It can transition after scheduling or I/O events.", page_number=4)],
            threshold=None,
            qa_document=True,
            carryover_question=carryover,
        )

        self.assertEqual(next_carryover, "What is a process state?")
        self.assertTrue(second_page_drafts[0].metadata["qa_continuation"])
        self.assertIn("Question: What is a process state?", second_page_drafts[0].text)

    def test_detects_question_answer_documents_from_structured_blocks(self) -> None:
        page_blocks = [
            [_block(f"{index}. What is concept {index}?") for index in range(1, 5)],
            [_block(f"{index}. What is concept {index}?") for index in range(5, 9)],
            [_block(f"{index}. What is concept {index}?") for index in range(9, 13)],
        ]

        self.assertTrue(IngestionChunkBuilder.is_question_answer_document(page_blocks))


if __name__ == "__main__":
    unittest.main()
