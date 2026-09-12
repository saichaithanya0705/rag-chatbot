from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.services.rag.rag_grounding import compose_fallback_answer, ungrounded_answer_message
from app.services.rag.rag_retrieval import RagRetrievalEngine
from app.services.rag.rag_types import CandidateChunk
from app.services.providers.reranker_service import RerankerService
from test_chat_pipeline_resilience import (
    _rag_service, _prepared, _context, _InterruptedGenerationClient, _ConnectedRequest,
)
from app.routers.chat import _stream_finalized_answer


def fallback(question, *texts):
    return compose_fallback_answer(
        [SimpleNamespace(kind="pdf", text=text) for text in texts],
        question=question, generation_warning="provider failed",
        extract_direct_qa_pair=lambda text: None,
    )


def test_unrelated_evidence_abstains_without_citations():
    result = fallback("What is acute pancreatitis?", "Hello World")
    assert result.answer == ungrounded_answer_message()
    assert not result.citation_contexts


def test_small_useful_excerpt_survives_among_unrelated_sources():
    text = "Acute pancreatitis is sudden inflammation of the pancreas."
    result = fallback("What is acute pancreatitis?", "Hello World", text)
    assert result.answer == text
    assert len(result.citation_contexts) == 1


def test_unrelated_leading_sentence_is_not_copied():
    result = fallback("What is a process?", "Hello World. A process is a program in execution.")
    assert result.answer == "A process is a program in execution."


def test_missing_question_terms_fail_closed():
    assert not fallback("Explain this", "Hello World").citation_contexts


@pytest.mark.asyncio
async def test_interrupted_stream_rejects_original_hello_world_failure():
    prepared = _prepared()
    prepared.question = "What is acute pancreatitis?"
    prepared.contexts = [replace(_context(), text="Hello World", excerpt="Hello World")]
    client = _InterruptedGenerationClient()
    result = await _stream_finalized_answer(
        container=SimpleNamespace(nvidia_client=client, rag_service=_rag_service(client)),
        prepared=prepared, thinking_enabled=False, http_request=_ConnectedRequest(),
    )
    assert result.answer == ungrounded_answer_message()
    assert result.citations == []


def engine(scores):
    result = object.__new__(RagRetrievalEngine)
    result._top_k = 3
    result._web_search_score_threshold = 0.3
    result._reranker_service = SimpleNamespace(score_pairs=lambda *_: scores)
    return result


def candidate():
    return CandidateChunk(chunk_id="1", collection_id="all_chunks", document_id="d",
                          pdf_name="test.pdf", page_number=1, chunk_index=0, text="Hello World")


@pytest.mark.parametrize("score", [None, float("nan"), float("inf"), -1.0, 0.0, 0.2])
def test_unknown_or_weak_relevance_requests_web(score):
    assert engine([]).should_use_web_search(score)


@pytest.mark.parametrize("scores", [[], [float("nan")], [float("inf")], [-4.0], [0.0]])
def test_single_unrelated_or_invalid_candidate_is_not_accepted(scores):
    assert engine(scores)._rank_candidates(question="What is acute pancreatitis?", ordered_candidates=[candidate()]) == []


def test_single_relevant_candidate_is_scored_and_kept():
    result = engine([0.8])._rank_candidates(question="What is a process?", ordered_candidates=[candidate()])
    assert len(result) == 1
    assert result[0].rerank_score == 0.8
    assert not engine([]).should_use_web_search(0.8)


@pytest.mark.parametrize("rankings", [[], [{"index": 0, "logit": float("nan")}],
    [{"index": 2, "logit": 1}], [{"index": 0, "logit": 1}, {"index": 0, "logit": 2}]])
def test_bad_provider_ranking_uses_lexical_fallback(rankings):
    service = RerankerService(
        "model",
        nvidia_base_url="http://localhost:9000/v1",
        nvidia_api_key="test-key",
    )
    with patch("app.services.providers.reranker_service.httpx.Client") as client:
        client.return_value.__enter__.return_value.post.return_value.json.return_value = {"rankings": rankings}
        assert service.score_pairs("acute pancreatitis", ["Hello World"]) == [0.0]


def test_shared_adjective_does_not_make_an_unrelated_condition_relevant():
    result = fallback("What is acute pancreatitis?", "Acute appendicitis affects the appendix.")
    assert result.answer == ungrounded_answer_message()
    assert not result.citation_contexts


def test_dominant_document_still_scores_every_passage():
    candidates = [replace(candidate(), chunk_id=str(index)) for index in range(3)]
    service = engine([0.0, 0.9, -2.0])
    result = service._rank_candidates(question="What is a process?", ordered_candidates=candidates)
    assert [item.chunk_id for item in result] == ["1"]
