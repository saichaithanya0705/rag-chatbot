from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from app.services.rag.rag_grounding import ungrounded_answer_message
from quality_evals.core import (
    EvalCase,
    EvalContext,
    EvalExpectation,
    EvalOutput,
    EvalResult,
    load_cases,
    precision_recall,
    score_case,
    summarize,
)
from quality_evals.judge import judge_case, parse_judge_output
from quality_evals.targets import run_target


DATASET = Path(__file__).resolve().parents[1] / "quality_evals" / "datasets" / "rag_core.jsonl"


class _RetryingJudgeClient:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_answer(self, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return SimpleNamespace(response="not json")
        return SimpleNamespace(
            response=json.dumps(
                {
                    "correct": True,
                    "relevant": True,
                    "faithful": True,
                    "safe": True,
                    "reason": "The answer is supported by the supplied evidence.",
                }
            )
        )


class _ProgrammingErrorJudgeClient:
    async def generate_answer(self, **_kwargs):
        raise KeyError("unexpected judge response wiring error")


class QualityEvalCoreTests(unittest.TestCase):
    def test_precision_and_recall_use_unique_context_ids(self) -> None:
        precision, recall = precision_recall(["a", "a", "noise"], {"a", "b"})

        self.assertEqual(precision, 0.5)
        self.assertEqual(recall, 0.5)

    def test_judge_output_requires_typed_pass_fail_fields(self) -> None:
        verdict = parse_judge_output(
            'prefix {"correct":true,"relevant":true,"faithful":false,'
            '"safe":true,"reason":"Unsupported detail."} suffix'
        )

        self.assertFalse(verdict["faithful"])
        with self.assertRaises(ValueError):
            parse_judge_output('{"correct":"yes","reason":"invalid"}')

    def test_adversarial_case_fails_when_forbidden_claim_is_cited(self) -> None:
        case = EvalCase(
            id="mixed-claim",
            target="generation",
            category="adversarial_grounding",
            question="What is a process?",
            contexts=(EvalContext(id="process", text="A process is a program in execution."),),
            expected=EvalExpectation(
                abstain=True,
                forbidden_phrases=("cures cancer",),
            ),
        )
        output = EvalOutput(
            answer="A process is a program in execution and cures cancer.",
            citation_ids=("process",),
        )

        result = score_case(
            case,
            output,
            abstention_text=ungrounded_answer_message(),
        )

        self.assertFalse(result.passed)
        self.assertIn("answer contains forbidden phrase 'cures cancer'", result.failures)

    def test_curated_dataset_is_valid_and_covers_every_eval_boundary(self) -> None:
        cases = load_cases(DATASET)

        self.assertGreaterEqual(len(cases), 15)
        self.assertEqual({case.target for case in cases}, {"fallback", "generation", "intent", "retrieval"})
        self.assertTrue(any("adversarial" in case.tags for case in cases))
        self.assertTrue(any("failure-path" in case.tags for case in cases))

    def test_focused_run_does_not_fail_gates_for_metrics_it_did_not_execute(self) -> None:
        result = EvalResult(
            case_id="one-case",
            target="retrieval",
            category="retrieval_quality",
            passed=True,
            scores={"context_recall": 1.0},
            failures=(),
            output=EvalOutput(context_ids=("context",)),
        )

        summary = summarize(
            [result],
            {"case_pass_rate": 1.0, "context_recall": 1.0, "intent_accuracy": 1.0},
        )

        self.assertTrue(summary.passed)


class QualityEvalExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_recorded_cases_execute_without_external_services(self) -> None:
        cases = load_cases(DATASET)

        outputs = [await run_target(case) for case in cases]

        self.assertEqual(len(outputs), len(cases))
        self.assertTrue(any(output.answer for output in outputs))
        self.assertTrue(any(output.intent for output in outputs))
        self.assertTrue(any(output.context_ids for output in outputs))

    async def test_model_judge_retries_malformed_output_and_logs_each_decision(self) -> None:
        case = EvalCase(
            id="judge-retry",
            target="generation",
            category="answer_quality",
            question="What is a process?",
            contexts=(EvalContext(id="process", text="A process is a program in execution."),),
            expected=EvalExpectation(abstain=False, context_ids=("process",)),
            reference_answer="A process is a program in execution.",
        )
        client = _RetryingJudgeClient()
        with TemporaryDirectory() as directory:
            log_path = Path(directory) / "judge.jsonl"

            verdict = await judge_case(
                case,
                EvalOutput(answer="A process is a program in execution."),
                client=client,
                log_path=log_path,
            )
            records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

        self.assertTrue(verdict["correct"])
        self.assertEqual(client.calls, 2)
        self.assertEqual(len(records), 2)
        self.assertIsNotNone(records[0]["error"])
        self.assertIsNone(records[1]["error"])

    async def test_model_judge_does_not_mask_programming_errors_as_model_failures(self) -> None:
        case = EvalCase(
            id="judge-programming-error",
            target="generation",
            category="answer_quality",
            question="What is a process?",
            contexts=(EvalContext(id="process", text="A process is a program in execution."),),
            expected=EvalExpectation(abstain=False, context_ids=("process",)),
            reference_answer="A process is a program in execution.",
        )
        with TemporaryDirectory() as directory:
            with self.assertRaises(KeyError):
                await judge_case(
                    case,
                    EvalOutput(answer="A process is a program in execution."),
                    client=_ProgrammingErrorJudgeClient(),
                    log_path=Path(directory) / "judge.jsonl",
                )


if __name__ == "__main__":
    unittest.main()
