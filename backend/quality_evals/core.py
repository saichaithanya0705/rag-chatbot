from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from statistics import fmean
from typing import Any, Iterable


VALID_TARGETS = frozenset({"fallback", "generation", "intent", "retrieval"})
VALID_CONTEXT_KINDS = frozenset({"pdf", "web"})


@dataclass(frozen=True)
class EvalContext:
    id: str
    text: str
    kind: str = "pdf"
    pdf_name: str | None = None
    page_number: int | None = None
    chunk_index: int | None = None
    url: str | None = None
    title: str | None = None
    rerank_score: float | None = None


@dataclass(frozen=True)
class EvalExpectation:
    abstain: bool | None = None
    intent: str | None = None
    context_ids: tuple[str, ...] = ()
    required_phrases: tuple[str, ...] = ()
    forbidden_phrases: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalCase:
    id: str
    target: str
    category: str
    question: str
    contexts: tuple[EvalContext, ...]
    expected: EvalExpectation
    recorded_output: str | None = None
    reference_answer: str | None = None
    history: tuple[dict[str, str], ...] = ()
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvalOutput:
    answer: str = ""
    context_ids: tuple[str, ...] = ()
    citation_ids: tuple[str, ...] = ()
    intent: str | None = None
    raw_output: str | None = None
    latency_ms: float = 0.0


@dataclass(frozen=True)
class EvalResult:
    case_id: str
    target: str
    category: str
    passed: bool
    scores: dict[str, float]
    failures: tuple[str, ...]
    output: EvalOutput
    judge: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "target": self.target,
            "category": self.category,
            "passed": self.passed,
            "scores": self.scores,
            "failures": list(self.failures),
            "output": {
                "answer": self.output.answer,
                "context_ids": list(self.output.context_ids),
                "citation_ids": list(self.output.citation_ids),
                "intent": self.output.intent,
                "raw_output": self.output.raw_output,
                "latency_ms": self.output.latency_ms,
            },
            "judge": self.judge,
        }


@dataclass(frozen=True)
class EvalSummary:
    passed: bool
    case_count: int
    passed_case_count: int
    metrics: dict[str, float]
    gate_failures: tuple[str, ...]
    results: tuple[EvalResult, ...] = field(repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "case_count": self.case_count,
            "passed_case_count": self.passed_case_count,
            "metrics": self.metrics,
            "gate_failures": list(self.gate_failures),
            "results": [result.to_dict() for result in self.results],
        }


def load_cases(path: Path) -> list[EvalCase]:
    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as error:
                raise ValueError(f"{path}:{line_number}: invalid JSON: {error.msg}") from error
            case = _parse_case(payload, source=f"{path}:{line_number}")
            if case.id in seen_ids:
                raise ValueError(f"{path}:{line_number}: duplicate case id {case.id!r}")
            seen_ids.add(case.id)
            cases.append(case)
    if not cases:
        raise ValueError(f"{path}: dataset contains no evaluation cases")
    return cases


def _parse_case(payload: Any, *, source: str) -> EvalCase:
    if not isinstance(payload, dict):
        raise ValueError(f"{source}: each case must be a JSON object")

    case_id = _required_text(payload, "id", source)
    target = _required_text(payload, "target", source)
    if target not in VALID_TARGETS:
        raise ValueError(f"{source}: target must be one of {sorted(VALID_TARGETS)}")
    category = _required_text(payload, "category", source)
    question = _required_text(payload, "question", source)

    raw_contexts = payload.get("contexts", [])
    if not isinstance(raw_contexts, list):
        raise ValueError(f"{source}: contexts must be a list")
    contexts = tuple(_parse_context(item, source=source) for item in raw_contexts)
    context_ids = [context.id for context in contexts]
    if len(context_ids) != len(set(context_ids)):
        raise ValueError(f"{source}: context ids must be unique")

    raw_expected = payload.get("expected")
    if not isinstance(raw_expected, dict):
        raise ValueError(f"{source}: expected must be an object")
    expected = EvalExpectation(
        abstain=_optional_bool(raw_expected, "abstain", source),
        intent=_optional_text(raw_expected.get("intent")),
        context_ids=_text_tuple(raw_expected.get("context_ids", []), "context_ids", source),
        required_phrases=_text_tuple(
            raw_expected.get("required_phrases", []), "required_phrases", source
        ),
        forbidden_phrases=_text_tuple(
            raw_expected.get("forbidden_phrases", []), "forbidden_phrases", source
        ),
    )
    unknown_context_ids = set(expected.context_ids) - set(context_ids)
    if unknown_context_ids:
        raise ValueError(
            f"{source}: expected context_ids are missing from contexts: "
            f"{sorted(unknown_context_ids)}"
        )

    recorded_output = _optional_text(payload.get("recorded_output"))
    if target in {"generation", "intent"} and recorded_output is None:
        raise ValueError(f"{source}: {target} cases require recorded_output for offline replay")
    if target == "retrieval":
        if not contexts:
            raise ValueError(f"{source}: retrieval cases require contexts")
        if any(context.rerank_score is None for context in contexts):
            raise ValueError(f"{source}: retrieval contexts require rerank_score")

    history_payload = payload.get("history", [])
    if not isinstance(history_payload, list) or any(not isinstance(item, dict) for item in history_payload):
        raise ValueError(f"{source}: history must be a list of objects")
    history = tuple(
        {"role": str(item.get("role", "")), "content": str(item.get("content", ""))}
        for item in history_payload
    )

    return EvalCase(
        id=case_id,
        target=target,
        category=category,
        question=question,
        contexts=contexts,
        expected=expected,
        recorded_output=recorded_output,
        reference_answer=_optional_text(payload.get("reference_answer")),
        history=history,
        tags=_text_tuple(payload.get("tags", []), "tags", source),
    )


def _parse_context(payload: Any, *, source: str) -> EvalContext:
    if not isinstance(payload, dict):
        raise ValueError(f"{source}: every context must be an object")
    context_id = _required_text(payload, "id", source)
    text = _required_text(payload, "text", source)
    kind = _optional_text(payload.get("kind")) or "pdf"
    if kind not in VALID_CONTEXT_KINDS:
        raise ValueError(f"{source}: context kind must be one of {sorted(VALID_CONTEXT_KINDS)}")
    score = payload.get("rerank_score")
    if score is not None and (isinstance(score, bool) or not isinstance(score, (int, float))):
        raise ValueError(f"{source}: rerank_score must be numeric or null")
    return EvalContext(
        id=context_id,
        text=text,
        kind=kind,
        pdf_name=_optional_text(payload.get("pdf_name")),
        page_number=_optional_int(payload.get("page_number"), "page_number", source),
        chunk_index=_optional_int(payload.get("chunk_index"), "chunk_index", source),
        url=_optional_text(payload.get("url")),
        title=_optional_text(payload.get("title")),
        rerank_score=float(score) if score is not None else None,
    )


def score_case(
    case: EvalCase,
    output: EvalOutput,
    *,
    abstention_text: str,
    judge: dict[str, Any] | None = None,
) -> EvalResult:
    scores: dict[str, float] = {}
    failures: list[str] = []
    expected = case.expected
    actual_abstain = output.answer.strip() == abstention_text.strip()

    if expected.abstain is not None:
        score = float(actual_abstain == expected.abstain)
        scores["abstention_accuracy"] = score
        if not score:
            failures.append(
                f"expected abstain={expected.abstain}, observed abstain={actual_abstain}"
            )

    if expected.intent is not None:
        score = float(output.intent == expected.intent)
        scores["intent_accuracy"] = score
        if not score:
            failures.append(f"expected intent {expected.intent!r}, observed {output.intent!r}")

    expected_ids = set(expected.context_ids)
    if case.target == "retrieval":
        precision, recall = precision_recall(output.context_ids, expected_ids)
        scores["context_precision"] = precision
        scores["context_recall"] = recall
        if expected_ids:
            scores["reciprocal_rank"] = reciprocal_rank(output.context_ids, expected_ids)
        if recall < 1.0:
            failures.append("retrieval missed one or more required contexts")
        if any(context_id not in expected_ids for context_id in output.context_ids):
            failures.append("retrieval retained one or more irrelevant contexts")

    if case.target in {"fallback", "generation"}:
        precision, recall = precision_recall(output.citation_ids, expected_ids)
        scores["citation_precision"] = precision
        scores["citation_recall"] = recall
        if set(output.citation_ids) - expected_ids:
            failures.append("answer cited context outside the expected evidence set")
        if expected_ids - set(output.citation_ids):
            failures.append("answer omitted one or more expected citations")

    lowered_answer = output.answer.casefold()
    phrase_hits = [phrase.casefold() in lowered_answer for phrase in expected.required_phrases]
    if phrase_hits:
        scores["required_fact_recall"] = sum(phrase_hits) / len(phrase_hits)
        for phrase, present in zip(expected.required_phrases, phrase_hits, strict=True):
            if not present:
                failures.append(f"answer is missing required phrase {phrase!r}")

    forbidden_hits = [phrase.casefold() in lowered_answer for phrase in expected.forbidden_phrases]
    if forbidden_hits:
        scores["forbidden_fact_avoidance"] = 1.0 - (sum(forbidden_hits) / len(forbidden_hits))
        for phrase, present in zip(expected.forbidden_phrases, forbidden_hits, strict=True):
            if present:
                failures.append(f"answer contains forbidden phrase {phrase!r}")

    if judge is not None:
        for key in ("correct", "relevant", "faithful", "safe"):
            value = judge.get(key)
            if isinstance(value, bool):
                scores[f"judge_{key}"] = float(value)
                if not value:
                    failures.append(f"model judge marked {key}=false")

    return EvalResult(
        case_id=case.id,
        target=case.target,
        category=case.category,
        passed=not failures,
        scores=scores,
        failures=tuple(failures),
        output=output,
        judge=judge,
    )


def precision_recall(actual_ids: Iterable[str], expected_ids: set[str]) -> tuple[float, float]:
    actual = list(dict.fromkeys(actual_ids))
    actual_set = set(actual)
    precision = len(actual_set & expected_ids) / len(actual_set) if actual_set else float(not expected_ids)
    recall = len(actual_set & expected_ids) / len(expected_ids) if expected_ids else float(not actual_set)
    return precision, recall


def reciprocal_rank(actual_ids: Iterable[str], expected_ids: set[str]) -> float:
    for index, context_id in enumerate(actual_ids, start=1):
        if context_id in expected_ids:
            return 1.0 / index
    return 0.0


def summarize(results: list[EvalResult], thresholds: dict[str, float]) -> EvalSummary:
    if not results:
        raise ValueError("cannot summarize an empty evaluation run")
    metric_values: dict[str, list[float]] = {}
    for result in results:
        for name, value in result.scores.items():
            metric_values.setdefault(name, []).append(value)

    metrics = {
        "case_pass_rate": sum(result.passed for result in results) / len(results),
        **{name: fmean(values) for name, values in sorted(metric_values.items())},
    }
    for category in sorted({result.category for result in results}):
        category_results = [result for result in results if result.category == category]
        metrics[f"category.{category}.pass_rate"] = (
            sum(result.passed for result in category_results) / len(category_results)
        )

    gate_failures = tuple(
        f"{name}={metrics[name]:.3f} is below minimum {minimum:.3f}"
        for name, minimum in thresholds.items()
        if name in metrics and metrics[name] < minimum
    )
    return EvalSummary(
        passed=not gate_failures,
        case_count=len(results),
        passed_case_count=sum(result.passed for result in results),
        metrics=metrics,
        gate_failures=gate_failures,
        results=tuple(results),
    )


def load_thresholds(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not payload:
        raise ValueError(f"{path}: thresholds must be a non-empty JSON object")
    thresholds: dict[str, float] = {}
    for name, value in payload.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{path}: threshold {name!r} must be numeric")
        numeric = float(value)
        if not 0.0 <= numeric <= 1.0:
            raise ValueError(f"{path}: threshold {name!r} must be between 0 and 1")
        thresholds[str(name)] = numeric
    return thresholds


def _required_text(payload: dict[str, Any], key: str, source: str) -> str:
    value = _optional_text(payload.get(key))
    if value is None:
        raise ValueError(f"{source}: {key} must be a non-empty string")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _text_tuple(value: Any, key: str, source: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(_optional_text(item) is None for item in value):
        raise ValueError(f"{source}: {key} must be a list of non-empty strings")
    return tuple(str(item).strip() for item in value)


def _optional_bool(payload: dict[str, Any], key: str, source: str) -> bool | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{source}: {key} must be a boolean")
    return value


def _optional_int(value: Any, key: str, source: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{source}: {key} must be an integer or null")
    return value
