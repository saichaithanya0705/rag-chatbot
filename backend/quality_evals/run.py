from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.services.providers.nvidia_client import NvidiaClient
from app.services.rag.rag_grounding import ungrounded_answer_message
from quality_evals.core import load_cases, load_thresholds, score_case, summarize
from quality_evals.judge import JudgeError, judge_case
from quality_evals.targets import run_target


EVAL_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET = EVAL_ROOT / "datasets" / "rag_core.jsonl"
DEFAULT_THRESHOLDS = EVAL_ROOT / "thresholds.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run deterministic or live RAG quality evaluations.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--thresholds", type=Path, default=DEFAULT_THRESHOLDS)
    parser.add_argument("--case", action="append", dest="case_ids", help="Run only a named case; repeatable.")
    parser.add_argument(
        "--live-model",
        action="store_true",
        help="Call the configured NVIDIA model for generation and intent cases instead of replaying recorded outputs.",
    )
    parser.add_argument(
        "--judge",
        action="store_true",
        help="Use a validated pass/fail NVIDIA model judge for answer cases.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/eval-latest.json"),
        help="JSON result artifact path, relative to the backend directory by default.",
    )
    parser.add_argument(
        "--judge-log",
        type=Path,
        default=Path("data/eval-judge.log"),
        help="Append-only judge prompt/output log.",
    )
    return parser


async def run_evaluations(args: argparse.Namespace) -> dict[str, Any]:
    cases = load_cases(args.dataset)
    if args.case_ids:
        requested = set(args.case_ids)
        cases = [case for case in cases if case.id in requested]
        missing = requested - {case.id for case in cases}
        if missing:
            raise ValueError(f"unknown case ids: {sorted(missing)}")

    target_client = _build_client() if args.live_model else None
    judge_client = _build_client(model=os.getenv("RAG_EVAL_JUDGE_MODEL")) if args.judge else None
    results = []
    try:
        for case in cases:
            output = await run_target(case, live_client=target_client)
            verdict = None
            if judge_client is not None and case.target in {"fallback", "generation"}:
                try:
                    verdict = await judge_case(
                        case,
                        output,
                        client=judge_client,
                        log_path=args.judge_log,
                    )
                except JudgeError as error:
                    verdict = {
                        "correct": False,
                        "relevant": False,
                        "faithful": False,
                        "safe": False,
                        "reason": str(error),
                    }
            results.append(
                score_case(
                    case,
                    output,
                    abstention_text=ungrounded_answer_message(),
                    judge=verdict,
                )
            )
    finally:
        if target_client is not None:
            await target_client.aclose()
        if judge_client is not None:
            await judge_client.aclose()

    summary = summarize(results, load_thresholds(args.thresholds))
    artifact = {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(args.dataset.resolve()),
        "mode": "live" if args.live_model else "recorded",
        "judge_enabled": bool(args.judge),
        **summary.to_dict(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return artifact


def _build_client(*, model: str | None = None) -> NvidiaClient:
    settings = get_settings()
    if not settings.nvidia_api_key:
        raise RuntimeError("RAG_NVIDIA_API_KEY or NVIDIA_API_KEY is required for live evals")
    return NvidiaClient(
        base_url=settings.nvidia_base_url,
        embed_model=settings.embed_model,
        chat_model=model or settings.chat_model,
        nvidia_base_url=settings.nvidia_base_url,
        nvidia_api_key=settings.nvidia_api_key,
        expected_embedding_dimensions=settings.embedding_dimensions,
        local_embedding_cache_dir=settings.model_cache_dir,
    )


def main() -> int:
    args = build_parser().parse_args()
    artifact = asyncio.run(run_evaluations(args))
    print(json.dumps({key: artifact[key] for key in ("passed", "case_count", "passed_case_count", "metrics", "gate_failures")}, indent=2))
    return 0 if artifact["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
