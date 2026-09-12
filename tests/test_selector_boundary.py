"""NI4 fixtures for profiling budgets and held-out reference isolation."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from studies.energy_diagnosis.analysis import (
    BudgetExhaustedError,
    ProfileResult,
    ProfilingBudget,
    ReferenceAccessError,
    SelectorBoundary,
    SelectorBoundaryError,
    SelectorConflictError,
)


SHA = "a" * 64
CANDIDATES = ("C00", "C01", "C02", "C03")


class FixtureClock:
    def __init__(self) -> None:
        self.value = 1_000

    def __call__(self) -> int:
        self.value += 100
        return self.value


def success(candidate_id: str) -> ProfileResult:
    return ProfileResult(
        status="success", duration_s=1.0, energy_j=2.0, energy_reason="",
        features={"candidate": candidate_id, "score": 1.0},
    )


class SelectorBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.clock = FixtureClock()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def boundary(self, *, profiler=success, budget: ProfilingBudget | None = None) -> SelectorBoundary:
        return SelectorBoundary(
            self.root / "selector.sqlite3",
            session_id="fixture-heldout-goal-01",
            selector_revision="dummy-selector-v1",
            development_data_sha256=SHA,
            candidates=CANDIDATES,
            allowed_features=("candidate", "score"),
            budget=budget or ProfilingBudget(max_queries=2, max_duration_s=10.0, max_energy_j=10.0),
            profiler=profiler,
            clock_ns=self.clock,
        )

    def test_reference_is_absent_from_selector_capability_and_exports_until_sealed(self) -> None:
        hidden = {candidate: {"secret-reference-marker": candidate} for candidate in CANDIDATES}
        with self.boundary() as boundary:
            with self.assertRaises(ReferenceAccessError):
                boundary.open_reference(hidden)
            with self.assertRaises(ReferenceAccessError):
                boundary.export_reference(self.root / "too-early")

            denied: list[str] = []

            def dummy_selector(api) -> None:
                for attribute in ("reference_outcomes", "open_reference", "reference_results"):
                    with self.assertRaises(AttributeError):
                        getattr(api, attribute)
                    denied.append(attribute)
                api.profile("C00")
                api.seal_recommendation("C01", "fixture-only deterministic choice")

            decision = boundary.run_selector(dummy_selector)
            self.assertEqual(["reference_outcomes", "open_reference", "reference_results"], denied)
            self.assertEqual("C01", decision.recommendation)
            selection = boundary.export_selection(self.root / "selection")
            self.assertNotIn("secret-reference-marker", "".join(path.read_text(encoding="utf-8") for path in selection.values()))

            opened = boundary.open_reference(hidden)
            self.assertEqual(hidden, opened)
            post_reference_selection = boundary.export_selection(self.root / "selection-after-reference")
            self.assertNotIn(
                "secret-reference-marker",
                "".join(path.read_text(encoding="utf-8") for path in post_reference_selection.values()),
            )
            with self.assertRaises(ReferenceAccessError):
                boundary.record_live_evaluation(setting_id="C03", evidence_sha256="b" * 64)
            boundary.record_live_evaluation(
                setting_id="C01", evidence_sha256="b" * 64, metadata={"simulated": True}
            )
            reference = boundary.export_reference(self.root / "reference")
            self.assertIn("secret-reference-marker", reference["reference"].read_text(encoding="utf-8"))
            live = json.loads(reference["live_evaluation"].read_text(encoding="utf-8"))
            self.assertEqual("C01", live["setting_id"])
            self.assertTrue(boundary.validate()["valid"])

    def test_all_query_costs_include_failures_and_exhaustion_leads_to_abstention(self) -> None:
        calls = 0

        def profiler(candidate_id: str) -> ProfileResult:
            nonlocal calls
            calls += 1
            if calls == 2:
                return ProfileResult(
                    status="failure", duration_s=2.0, energy_j=1.0, energy_reason="",
                    features={}, failure_reason=f"fixture failure for {candidate_id}",
                )
            return success(candidate_id)

        budget = ProfilingBudget(max_queries=2, max_duration_s=10.0, max_energy_j=10.0)
        with self.boundary(profiler=profiler, budget=budget) as boundary:
            def dummy_selector(api) -> None:
                api.profile("C00")
                api.profile("C01")
                with self.assertRaises(BudgetExhaustedError):
                    api.profile("C02")
                api.seal_abstention("fixture query budget exhausted")

            decision = boundary.run_selector(dummy_selector)
            self.assertEqual("abstention", decision.outcome)
            self.assertEqual(2, decision.profiling_query_count)
            self.assertEqual(3.0, decision.profiling_duration_s)
            self.assertEqual(3.0, decision.profiling_energy_j)
            query_lines = boundary.export_selection(self.root / "selection")["queries"].read_text(encoding="utf-8").splitlines()
            self.assertEqual(2, len(query_lines))
            failed = json.loads(query_lines[1])
            self.assertEqual("failure", failed["result"]["status"])
            self.assertEqual(2.0, failed["result"]["duration_s"])
            self.assertEqual(1.0, failed["result"]["energy_j"])
            with self.assertRaises(ReferenceAccessError):
                boundary.record_live_evaluation(setting_id="C00", evidence_sha256="b" * 64)

    def test_profiler_exception_is_recorded_and_unknown_energy_stops_energy_budget(self) -> None:
        def profiler(_candidate_id: str) -> ProfileResult:
            raise RuntimeError("fixture profiler failure")

        with self.boundary(
            profiler=profiler,
            budget=ProfilingBudget(max_queries=3, max_duration_s=10.0, max_energy_j=10.0),
        ) as boundary:
            def dummy_selector(api) -> None:
                result = api.profile("C00")
                self.assertEqual("failure", result.status)
                self.assertIsNone(result.energy_j)
                with self.assertRaises(BudgetExhaustedError):
                    api.profile("C01")
                api.seal_abstention("energy cost unavailable")

            decision = boundary.run_selector(dummy_selector)
            self.assertEqual(1, decision.unavailable_energy_queries)
            self.assertIsNone(decision.profiling_energy_j)
            report = boundary.validate()
            self.assertTrue(report["budget"]["exhausted"])
            self.assertIn("energy cost unavailable under an energy budget", report["budget"]["reasons"])

    def test_profiler_cannot_add_undeclared_reference_features(self) -> None:
        def leaky_profiler(_candidate_id: str) -> ProfileResult:
            return ProfileResult(
                status="success", duration_s=1.0, energy_j=1.0, energy_reason="",
                features={"reference_best_candidate": "forbidden-heldout-value"},
            )

        with self.boundary(profiler=leaky_profiler) as boundary:
            def dummy_selector(api) -> None:
                result = api.profile("C00")
                self.assertEqual("failure", result.status)
                self.assertEqual({}, result.features)
                api.seal_abstention("profiler violated declared feature interface")

            boundary.run_selector(dummy_selector)
            exports = boundary.export_selection(self.root / "selection")
            text = "".join(path.read_text(encoding="utf-8") for path in exports.values())
            self.assertNotIn("forbidden-heldout-value", text)
            self.assertIn("undeclared features", text)

    def test_seal_is_immutable_and_session_reopens_without_rerunning_selector(self) -> None:
        with self.boundary() as boundary:
            decision = boundary.run_selector(
                lambda api: api.seal_recommendation("C02", "fixture recommendation")
            )
            first = {name: path.read_bytes() for name, path in boundary.export_selection(self.root / "first").items()}
            with self.assertRaises(SelectorConflictError):
                boundary.seal_recommendation("C03", "post-hoc replacement")
            with self.assertRaises(SelectorConflictError):
                boundary.profile("C00")

        with self.boundary() as reopened:
            self.assertEqual(decision, reopened.decision())
            with self.assertRaises(SelectorConflictError):
                reopened.run_selector(lambda api: api.seal_abstention("must not rerun"))
            second = {name: path.read_bytes() for name, path in reopened.export_selection(self.root / "second").items()}
            self.assertEqual(first, second)

        with self.assertRaises(SelectorConflictError):
            SelectorBoundary(
                self.root / "selector.sqlite3", session_id="fixture-heldout-goal-01",
                selector_revision="changed-selector", development_data_sha256=SHA,
                candidates=CANDIDATES, allowed_features=("candidate", "score"),
                budget=ProfilingBudget(2, 10.0, 10.0),
                profiler=success, clock_ns=self.clock,
            )

    def test_selector_failure_is_sealed_as_abstention_before_propagation(self) -> None:
        with self.boundary() as boundary:
            def broken_selector(_api) -> None:
                raise ValueError("fixture selector bug")

            with self.assertRaisesRegex(ValueError, "fixture selector bug"):
                boundary.run_selector(broken_selector)
            decision = boundary.decision()
            self.assertEqual("abstention", decision.outcome)
            self.assertIn("ValueError", decision.abstention_reason)
            boundary.open_reference({candidate: {"score": 1} for candidate in CANDIDATES})

    def test_tampered_sealed_decision_is_detected(self) -> None:
        with self.boundary() as boundary:
            boundary.seal_recommendation("C01", "fixture recommendation")
            row = boundary._db.execute(
                "SELECT decision_json FROM selector_sessions WHERE session_id = ?", (boundary.session_id,)
            ).fetchone()
            changed = json.loads(row["decision_json"])
            changed["recommendation"] = "C03"
            boundary._db.execute(
                "UPDATE selector_sessions SET decision_json = ? WHERE session_id = ?",
                (json.dumps(changed, sort_keys=True, separators=(",", ":")), boundary.session_id),
            )
            report = boundary.validate()
            self.assertFalse(report["valid"])
            self.assertIn("sealed decision content hash mismatch", report["errors"])

    def test_invalid_costs_candidates_and_reference_coverage_are_rejected(self) -> None:
        with self.assertRaises(SelectorBoundaryError):
            ProfileResult("success", float("nan"), 1.0, "", {})
        with self.assertRaises(SelectorBoundaryError):
            ProfileResult("success", 1.0, float("inf"), "", {})
        with self.assertRaises(SelectorBoundaryError):
            SelectorBoundary(
                self.root / "bad.sqlite3", session_id="fixture", selector_revision="dummy",
                development_data_sha256=SHA, candidates=("C00", "C00"),
                allowed_features=("candidate", "score"),
                budget=ProfilingBudget(1, 1.0), profiler=success, clock_ns=self.clock,
            )
        with self.boundary() as boundary:
            boundary.seal_abstention("fixture")
            with self.assertRaises(SelectorBoundaryError):
                boundary.open_reference({"C00": {"score": 1}})


if __name__ == "__main__":
    unittest.main()
