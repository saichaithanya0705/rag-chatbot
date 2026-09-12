# RAG quality evaluations

This suite measures the probabilistic boundaries of the application separately from deterministic unit tests. It uses recorded model outputs by default, so CI is repeatable and does not require provider credentials; the same cases can call the configured NVIDIA model with `--live-model`.

## Evaluation map

| Boundary | Why an eval is needed | Metrics |
| --- | --- | --- |
| Intent routing | Model classification can change retrieval/tool routing | exact intent accuracy, malformed-output fallback |
| Retrieval and reranking | Relevant evidence can be missed or noise can be retained | context precision, context recall, reciprocal rank |
| Sparse-evidence fallback | Provider failures must not turn unrelated chunks into answers | abstention accuracy, required/forbidden facts, citation precision/recall |
| Grounded generation | Plausible prose and source markers can still contain unsupported claims | citation precision/recall, abstention, adversarial pass rate |
| Semantic answer quality | Correctness and faithfulness are not fully captured by string rules | optional rubric-based model judge with validated JSON and retry |
| Parsing, persistence, API schemas | These paths are deterministic | keep them in pytest integration/unit tests rather than adding fuzzy graders |

The dataset contains typical, edge, failure-path, sparse-corpus, and adversarial examples. Add production failures as new cases, preserve a held-out set for model or prompt selection, and calibrate judge decisions against human labels before trusting the judge at scale.

## Run

From `backend`:

```powershell
python -m quality_evals.run
```

The command writes the gitignored artifact `data/eval-latest.json` and exits non-zero when a quality gate fails. Focus one or more cases with `--case CASE_ID`, replay the current configured model with `--live-model`, and enable the rubric judge with `--judge`.

Live modes require `RAG_NVIDIA_API_KEY` or `NVIDIA_API_KEY`. Set `RAG_EVAL_JUDGE_MODEL` to use a judge model different from the target model; this is preferred because judging a model with itself can create correlated errors. Judge calls append the prompt, raw output, validated verdict, and errors to the gitignored `data/eval-judge.log`; that log can contain evaluated evidence, so treat it as sensitive local data.

## Why this shape

The suite follows current guidance to use task-specific evals, curated examples, separate retrieval and generation metrics, continuous regression gates, and explicit edge/adversarial cases. It uses deterministic code graders wherever the expected behavior is objective, then reserves model judging for semantic correctness, relevance, faithfulness, and prompt-injection safety.

Primary references:

- https://developers.openai.com/api/docs/guides/evaluation-best-practices
- https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/
- https://docs.langchain.com/langsmith/evaluation-concepts
- https://www.nist.gov/itl/ai-risk-management-framework
