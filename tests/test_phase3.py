import unittest
from dataclasses import replace
from datetime import datetime, timezone

from phase3_finality import (
    OperationState,
    POLICIES,
    ServiceGuarantees,
    build_scenarios,
    classify_evidence,
    evaluate,
    guarantee_aware_controller,
    blind_retry,
    idempotency_only,
    requested_state,
    run_comparison,
)


class PhaseThreeFinalityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.now = datetime.now(timezone.utc)
        cls.scenarios = {item.name: item for item in build_scenarios()}

    def test_local_request_is_not_remote_in_flight_or_commit(self):
        self.assertEqual(requested_state(), OperationState.REQUESTED)

    def test_retry_policies_do_not_use_hidden_scenario_truth_as_confirmation(self):
        committed = self.scenarios["verified_commit_receipt"]
        for policy in (blind_retry, idempotency_only):
            with self.subTest(policy=policy.__name__):
                self.assertEqual(
                    policy(committed, self.now).state,
                    OperationState.UNKNOWN,
                )

    def test_absence_snapshot_without_terminal_guarantee_is_unknown(self):
        case = self.scenarios["commit_after_absence_snapshot"]
        self.assertEqual(
            classify_evidence(case.observations, case.guarantees),
            OperationState.UNKNOWN,
        )
        candidate = POLICIES["phase2_quorum_wait"](case, self.now)
        metrics = evaluate(case, candidate)
        self.assertEqual(metrics["duplicate_side_effects"], 1)
        self.assertEqual(metrics["unsafe_retries"], 1)

    def test_two_names_for_one_stale_cache_are_not_independent_proof(self):
        case = self.scenarios["shared_stale_cache_two_names"]
        self.assertEqual(
            case.observations[0].provenance_root,
            case.observations[1].provenance_root,
        )
        self.assertEqual(
            classify_evidence(case.observations, case.guarantees),
            OperationState.UNKNOWN,
        )
        candidate = POLICIES["phase2_quorum_wait"](case, self.now)
        metrics = evaluate(case, candidate)
        self.assertEqual(metrics["duplicate_side_effects"], 1)
        self.assertEqual(metrics["unsafe_retries"], 1)

    def test_independent_disagreement_is_conflicting_evidence(self):
        case = self.scenarios["independent_observations_disagree"]
        self.assertNotEqual(
            case.observations[0].provenance_root,
            case.observations[1].provenance_root,
        )
        self.assertEqual(
            classify_evidence(case.observations, case.guarantees),
            OperationState.CONFLICTING_EVIDENCE,
        )

    def test_authenticated_nonterminal_status_can_only_establish_in_flight(self):
        case = self.scenarios["cannot_establish_if_in_flight"]
        observation = case.observations[0]
        in_flight = replace(observation, state=OperationState.IN_FLIGHT)
        self.assertEqual(
            classify_evidence((in_flight,), case.guarantees),
            OperationState.UNKNOWN,
        )
        authoritative = replace(in_flight, authority=True)
        self.assertEqual(
            classify_evidence(
                (authoritative,),
                ServiceGuarantees(authoritative_status=True),
            ),
            OperationState.IN_FLIGHT,
        )

    def test_verified_terminal_receipt_and_primary_finality_confirm_commit(self):
        for name in ("verified_commit_receipt", "primary_consistent_commit"):
            case = self.scenarios[name]
            self.assertEqual(
                classify_evidence(case.observations, case.guarantees),
                OperationState.COMMITTED,
            )

    def test_mismatched_operation_and_payload_evidence_is_ignored(self):
        case = self.scenarios["mismatched_operation_or_payload"]
        self.assertEqual(
            classify_evidence(case.observations, case.guarantees),
            OperationState.UNKNOWN,
        )

    def test_delayed_commit_after_absence_is_deferred_by_safe_controller(self):
        case = self.scenarios["commit_after_absence_snapshot"]
        decision = guarantee_aware_controller(case, self.now)
        self.assertEqual(decision.action, "DEFER")
        self.assertFalse(decision.retry_safe)
        phase2 = POLICIES["phase2_quorum_wait"](case, self.now)
        phase2_metrics = evaluate(case, phase2)
        self.assertEqual(phase2_metrics["duplicate_side_effects"], 1)
        self.assertEqual(phase2_metrics["unsafe_retries"], 1)

    def test_idempotency_without_status_allows_only_same_payload_retry(self):
        case = self.scenarios["idempotency_without_status"]
        decision = guarantee_aware_controller(case, self.now)
        self.assertEqual(decision.action, "RETRY_SAME_KEY_CONFIRMED")
        self.assertTrue(decision.retry_safe)
        metrics = evaluate(case, decision)
        self.assertEqual(metrics["resolved_operations"], 1)
        self.assertEqual(metrics["duplicate_side_effects"], 0)

    def test_idempotency_without_verifiable_retry_receipt_stays_unknown(self):
        case = self.scenarios["idempotency_without_verifiable_retry_receipt"]
        decision = guarantee_aware_controller(case, self.now)
        self.assertEqual(decision.action, "RETRY_SAME_KEY_OUTCOME_UNKNOWN")
        self.assertTrue(decision.retry_safe)
        self.assertEqual(evaluate(case, decision)["deferred_unresolved"], 1)

    def test_non_atomic_idempotency_claim_does_not_authorize_retry(self):
        case = self.scenarios["idempotency_not_atomic_with_effect"]
        decision = guarantee_aware_controller(case, self.now)
        self.assertEqual(decision.action, "DEFER")
        self.assertFalse(decision.retry_safe)

    def test_service_without_idempotency_or_status_requires_deferral(self):
        case = self.scenarios["neither_idempotency_nor_authoritative_status"]
        decision = guarantee_aware_controller(case, self.now)
        metrics = evaluate(case, decision)
        self.assertEqual(decision.action, "DEFER")
        self.assertEqual(metrics["unsafe_retries"], 0)
        self.assertEqual(metrics["deferred_unresolved"], 1)

    def test_changed_payload_is_not_retried_under_same_idempotency_key(self):
        case = self.scenarios["changed_payload_same_key"]
        decision = guarantee_aware_controller(case, self.now)
        self.assertEqual(decision.action, "DEFER_PAYLOAD_MISMATCH")
        self.assertTrue(decision.payload_conflict)
        self.assertFalse(decision.retry_safe)

    def test_nonterminal_absence_and_stale_evidence_do_not_prove_finality(self):
        case = self.scenarios["authoritative_terminal_no_commit"]
        nonterminal_guarantees = ServiceGuarantees(
            authoritative_status=True,
            terminal_finality=False,
        )
        self.assertEqual(
            classify_evidence(
                case.observations,
                nonterminal_guarantees,
            ),
            OperationState.UNKNOWN,
        )
        stale = replace(case.observations[0], age_seconds=20)
        self.assertEqual(
            classify_evidence((stale,), case.guarantees),
            OperationState.UNKNOWN,
        )

    def test_all_policies_use_identical_cases_and_expose_phase2_false_quorum(self):
        scenarios, results = run_comparison()
        self.assertEqual(len(scenarios), 15)
        for result in results.values():
            self.assertEqual(result["totals"]["cases"], 300)
            self.assertEqual(
                set(result["per_scenario"]),
                {scenario.name for scenario in scenarios},
            )
        false_consensus = results["phase2_quorum_wait"]["per_scenario"][
            "false_independent_commit_agreement"
        ]
        self.assertEqual(false_consensus["false_commit_confirmations"], 20)
        self.assertEqual(
            results["guarantee_aware_controller"]["per_scenario"][
                "false_independent_commit_agreement"
            ]["deferred_unresolved"],
            20,
        )


if __name__ == "__main__":
    unittest.main()
