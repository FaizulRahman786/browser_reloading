import unittest
from dataclasses import replace
from datetime import datetime, timezone

from phase2_recovery import (
    POLICIES,
    build_cases,
    quorum_settlement_gate,
    run_benchmark,
)


class PhaseTwoPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = build_cases(datetime.now(timezone.utc))
        cls.results = run_benchmark(cls.cases)

    def test_all_policies_receive_identical_scenario_count(self):
        for result in self.results.values():
            self.assertEqual(result["totals"]["cases"], 200)
            self.assertEqual(set(result["per_case"]), {case.name for case in self.cases})

    def test_candidate_resolves_conflicting_fresh_two_to_one_evidence(self):
        case = self.results["quorum_settlement_gate"]["per_case"][
            "fresh_two_to_one_conflict"
        ]
        self.assertEqual(case["successfully_resolved"], 20)
        self.assertEqual(case["actions"], {"CONFIRM_COMMITTED": 20})
        baseline = self.results["evidence_deferral"]["per_case"][
            "fresh_two_to_one_conflict"
        ]
        self.assertEqual(baseline["deferred"], 20)

    def test_absence_quorum_waits_and_requires_a_fresh_post_settlement_read(self):
        case = next(
            item for item in self.cases
            if item.name == "settled_absence_consensus"
        )
        result = quorum_settlement_gate(case, datetime.now(timezone.utc))
        self.assertEqual(result.action, "RETRY")
        self.assertEqual(result.latency_ms, 1200)

        without_post_wait_read = replace(case, post_settlement_evidence=())
        result = quorum_settlement_gate(
            without_post_wait_read,
            datetime.now(timezone.utc),
        )
        self.assertEqual(result.action, "DEFER_SETTLEMENT_WINDOW")

    def test_candidate_fails_when_commit_arrives_after_declared_absence_bound(self):
        case = self.results["quorum_settlement_gate"]["per_case"][
            "late_commit_after_absence_and_declared_bound"
        ]
        self.assertEqual(case["duplicate_operations"], 20)
        self.assertEqual(case["unsafe_retries"], 20)
        self.assertEqual(case["actions"], {"RETRY": 20})

    def test_candidate_false_quorum_can_incorrectly_confirm(self):
        case = self.results["quorum_settlement_gate"]["per_case"][
            "false_commit_quorum"
        ]
        self.assertEqual(case["incorrectly_confirmed_commits"], 20)
        self.assertEqual(case["actions"], {"CONFIRM_COMMITTED": 20})

    def test_candidate_defers_single_inconsistent_or_untrusted_evidence(self):
        for scenario in (
            "single_inconsistent_absence_source",
            "untrusted_agreeing_sources",
            "no_status_and_no_remote_idempotency",
        ):
            with self.subTest(scenario=scenario):
                case = self.results["quorum_settlement_gate"]["per_case"][scenario]
                self.assertEqual(case["deferred"], 20)
                self.assertEqual(case["unsafe_retries"], 0)

    def test_changed_payload_is_rejected_by_candidate_and_idempotency_api(self):
        candidate = self.results["quorum_settlement_gate"]["per_case"][
            "changed_retry_payload"
        ]
        idempotent = self.results["idempotency_only"]["per_case"][
            "changed_retry_payload"
        ]
        blind = self.results["blind_retry"]["per_case"]["changed_retry_payload"]
        self.assertEqual(candidate["deferred"], 20)
        self.assertEqual(idempotent["payload_conflicts"], 20)
        self.assertEqual(blind["duplicate_operations"], 20)

    def test_candidate_reduces_duplicate_and_unsafe_retry_totals_but_adds_false_commits(self):
        candidate = self.results["quorum_settlement_gate"]["totals"]
        evidence = self.results["evidence_deferral"]["totals"]
        self.assertLess(
            candidate["duplicate_operations"],
            evidence["duplicate_operations"],
        )
        self.assertLess(candidate["unsafe_retries"], evidence["unsafe_retries"])
        self.assertGreater(
            candidate["incorrectly_confirmed_commits"],
            evidence["incorrectly_confirmed_commits"],
        )

    def test_candidate_has_higher_modeled_latency_than_idempotency_only(self):
        candidate = self.results["quorum_settlement_gate"]["totals"]
        idempotent = self.results["idempotency_only"]["totals"]
        self.assertGreater(candidate["latency_ms"], idempotent["latency_ms"])

    def test_each_policy_has_a_callable_implementation(self):
        self.assertEqual(
            set(POLICIES),
            {
                "blind_retry",
                "idempotency_only",
                "evidence_deferral",
                "quorum_settlement_gate",
            },
        )


if __name__ == "__main__":
    unittest.main()
