#!/usr/bin/env python3
"""
Benchmark dataset loader for Tier 1 standard benchmark tasks.

Downloads once, caches to data/benchmarks/ — no re-download per run.
Loads exact sample IDs for reproducibility across paper runs.
Supports GSM8K, HumanEval, TriviaQA, MMLU.

Paper reproducibility requirement: sample_id in tasks.yaml is the
canonical record. Same ID → same prompt → same expected answer across
all runs, providers, and machines.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Local cache dir — avoids re-download across experiment nights
BENCHMARK_CACHE_DIR = "data/benchmarks"

# Registry of supported datasets — extend here, never in callers
SUPPORTED_BENCHMARKS = {
    "gsm8k": {
        "hf_name": "gsm8k",
        "hf_config": "main",
        "split": "test",
        "question_field": "question",
        "answer_field": "answer",
    },
    "humaneval": {
        "hf_name": "openai_humaneval",
        "hf_config": None,
        "split": "test",
        "question_field": "prompt",
        "answer_field": "canonical_solution",
    },
    "triviaqa": {
        "hf_name": "trivia_qa",
        "hf_config": "rc",
        "split": "validation",
        "question_field": "question",
        "answer_field": "answer",
    },
    "mmlu": {
        "hf_name": "cais/mmlu",
        "hf_config": "all",
        "split": "test",
        "question_field": "question",
        "answer_field": "answer",
    },
}


class BenchmarkLoader:
    """
    Loads standard benchmark samples by exact ID.
    Caches dataset locally after first download.
    Thread-safe for read access — never writes during experiment runs.
    """

    def __init__(self, cache_dir: str = BENCHMARK_CACHE_DIR):
        """cache_dir must exist before experiments — created here if not."""
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        # In-memory cache across calls in same process — avoids repeated disk reads
        self._loaded: dict = {}

    def load(self, dataset: str, sample_ids: list) -> list:
        """
        Load specific samples by index from benchmark dataset.
        Returns list of {id, prompt, expected_answer, dataset, sample_id} dicts.
        Downloads once to BENCHMARK_CACHE_DIR, uses cache on subsequent calls.
        Raises ValueError if dataset not in SUPPORTED_BENCHMARKS.
        """
        if dataset not in SUPPORTED_BENCHMARKS:
            raise ValueError(
                f"Dataset '{dataset}' not supported. "
                f"Supported: {list(SUPPORTED_BENCHMARKS.keys())}"
            )

        ds = self._get_or_load(dataset)
        config = SUPPORTED_BENCHMARKS[dataset]
        results = []

        for sid in sample_ids:
            try:
                row = ds[int(sid)]
                prompt = self._build_prompt(dataset, row, config)
                answer = self._extract_answer(dataset, row, config)
                results.append({
                    "id": f"{dataset}_{sid}",
                    "sample_id": sid,
                    "dataset": dataset,
                    "prompt": prompt,
                    "expected_answer": answer,
                })
            except (IndexError, KeyError) as exc:
                logger.warning(
                    "BenchmarkLoader: sample_id=%s not found in %s: %s",
                    sid, dataset, exc,
                )

        return results

    def get_task_prompt(self, dataset: str, sample_id: int) -> dict:
        """
        Returns {prompt, expected_answer, difficulty} for one sample.
        Used by experiment_runner.resolve_task_prompt() for Tier 1 tasks.
        difficulty is always 'medium' for benchmarks — no dataset-level signal.
        """
        samples = self.load(dataset, [sample_id])
        if not samples:
            raise ValueError(f"Sample {sample_id} not found in {dataset}")

        sample = samples[0]
        return {
            "prompt": sample["prompt"],
            "expected_answer": sample["expected_answer"],
            "difficulty": "medium",
        }

    def _get_or_load(self, dataset: str):
        """
        Returns HuggingFace dataset split, loading from cache if available.
        Never re-downloads if local cache exists.
        """
        if dataset in self._loaded:
            return self._loaded[dataset]

        config = SUPPORTED_BENCHMARKS[dataset]
        try:
            # datasets library handles caching transparently via cache_dir
            from datasets import load_dataset
            ds = load_dataset(
                config["hf_name"],
                config["hf_config"],
                split=config["split"],
                cache_dir=str(self.cache_dir),
                trust_remote_code=False,  # never execute remote code
            )
            self._loaded[dataset] = ds
            logger.info("BenchmarkLoader: loaded %s (%d samples)", dataset, len(ds))
            return ds
        except Exception as exc:
            logger.error("BenchmarkLoader: failed to load %s: %s", dataset, exc)
            raise

    def _build_prompt(self, dataset: str, row: dict, config: dict) -> str:
        """
        Build task prompt from dataset row.
        GSM8K: question as-is.
        HumanEval: function signature + docstring.
        TriviaQA: question as-is.
        MMLU: question + lettered choices.
        """
        if dataset == "mmlu":
            # MMLU has choices list — must be formatted as MCQ
            choices = row.get("choices", [])
            letters = "ABCD"
            choices_str = "\n".join(
                f"{letters[i]}. {c}"
                for i, c in enumerate(choices)
                if i < len(letters)
            )
            return f"{row[config['question_field']]}\n{choices_str}"

        return str(row[config["question_field"]])

    def _extract_answer(self, dataset: str, row: dict, config: dict) -> str:
        """
        Extract expected answer from dataset row.
        GSM8K: answer field contains reasoning + #### final number — extract number.
        TriviaQA: answer is a dict with 'value' key.
        Others: use answer field directly.
        """
        raw = row[config["answer_field"]]

        if dataset == "gsm8k":
            # GSM8K answer format: "... #### 42" — extract the number after ####
            if "####" in str(raw):
                return str(raw).split("####")[-1].strip()
            return str(raw)

        if dataset == "triviaqa":
            # TriviaQA answer is dict: {"value": "...", "aliases": [...]}
            if isinstance(raw, dict):
                return str(raw.get("value", raw))
            return str(raw)

        if dataset == "mmlu":
            # MMLU answer is integer index 0-3 — convert to letter
            letters = "ABCD"
            try:
                return letters[int(raw)]
            except (ValueError, IndexError):
                return str(raw)

        return str(raw)
