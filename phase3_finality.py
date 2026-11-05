"""Local deterministic model for service-verifiable recovery finality."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable

from phase2_recovery import quorum_settlement_gate
from phase2_recovery import EXPECTED_OPERATION_ID as PHASE2_OPERATION_ID
from phase2_recovery import EXPECTED_PAYLOAD_HASH as PHASE2_PAYLOAD_HASH
from scenario11_evidence_freshness import Evidence


RETRY_LATENCY_MS = 100
STATUS_LATENCY_MS = 50
REPETITIONS = 20
OPERATION_ID = "phase3-op"
PAYLOAD_HASH = "phase3-payload"
MAX_EVIDENCE_AGE_SECONDS = 10


class OperationState(str, Enum):
    REQUESTED = "REQUESTED"
    IN_FLIGHT = "IN_FLIGHT"
    COMMITTED = "COMMITTED"
    PROVEN_NOT_COMMITTED = "PROVEN_NOT_COMMITTED"
    UNKNOWN = "UNKNOWN"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"


@dataclass(frozen=True)
class ServiceGuarantees:
    supports_idempotency: bool = False
    idempotency_atomic_with_effect: bool = False
    authoritative_status: bool = False
    terminal_finality: bool = False
    receipt_semantics_documented: bool = False

    @property
    def safe_idempotent_retry(self) -> bool:
        return (
            self.supports_idempotency
            and self.idempotency_atomic_with_effect
        )


@dataclass(frozen=True)
class Observation:
    source_id: str
    provenance_root: str
    operation_id: str
    payload_hash: str
    state: OperationState
    age_seconds: int = 0
    authenticated: bool = False
    authority: bool = False
    terminal: bool = False
    receipt_valid: bool = False


@dataclass(frozen=True)
class Scenario:
    name: str
    original_commits: bool
    guarantees: ServiceGuarantees
    observations: tuple[Observation, ...] = ()
    retry_payload_matches: bool = True
    elapsed_ms: int = 0
    duration_bound_ms: int = 1000
    post_bound_observations: tuple[Observation, ...] = ()
    independent_sources: bool = True


@dataclass(frozen=True)
class Decision:
    state: OperationState
    action: str
    side_effects: int
    latency_ms: int
    payload_conflict: bool = False
    retry_safe: bool = False
    commit_from_retry: bool = False


def requested_state() -> OperationState:
    """The controller's local intent record exists; no remote outcome implied."""
    return OperationState.REQUESTED


def classify_evidence(
    observations: tuple[Observation, ...],
    guarantees: ServiceGuarantees,
) -> OperationState:
    valid = [
        item
        for item in observations
        if item.operation_id == OPERATION_ID
        and item.payload_hash == PAYLOAD_HASH
        and 0 <= item.age_seconds <= MAX_EVIDENCE_AGE_SECONDS
        and item.authenticated
    ]
    if not valid:
        return OperationState.UNKNOWN

    strong_terminal = [
        item for item in valid
        if item.authority
        and item.terminal
        and item.state in {
            OperationState.COMMITTED,
            OperationState.PROVEN_NOT_COMMITTED,
        }
        and guarantees.authoritative_status
        and guarantees.terminal_finality
    ]
    receipts = [
        item for item in valid
        if item.state == OperationState.COMMITTED
        and item.receipt_valid
        and guarantees.receipt_semantics_documented
    ]
    decisive = strong_terminal + receipts
    decisive_states = {item.state for item in decisive}
    if len(decisive_states) > 1:
        return OperationState.CONFLICTING_EVIDENCE
    if decisive:
        return next(iter(decisive_states))

    roots_by_state: dict[OperationState, set[str]] = {}
    for item in valid:
        roots_by_state.setdefault(item.state, set()).add(item.provenance_root)

    nonterminal_states = {
        state
        for state, roots in roots_by_state.items()
        if roots
    }
    if len(nonterminal_states) > 1:
        return OperationState.CONFLICTING_EVIDENCE
    if nonterminal_states == {OperationState.IN_FLIGHT} and guarantees.authoritative_status:
        if any(item.authority and item.state == OperationState.IN_FLIGHT for item in valid):
            return OperationState.IN_FLIGHT

    # Agreement among non-authoritative sources is still only an observation.
    return OperationState.UNKNOWN


def _side_effects_after_retry(scenario: Scenario, *, deduplicated: bool) -> int:
    if deduplicated:
        return 1
    return int(scenario.original_commits) + 1


def _retry_decision(
    scenario: Scenario,
    *,
    safe_idempotency: bool,
    proven_not_committed: bool,
    latency_ms: int,
) -> Decision:
    if not scenario.retry_payload_matches:
        return Decision(
            OperationState.UNKNOWN,
            "DEFER_PAYLOAD_MISMATCH",
            int(scenario.original_commits),
            latency_ms,
            payload_conflict=safe_idempotency,
        )

    if safe_idempotency:
        effects = _side_effects_after_retry(scenario, deduplicated=True)
        # The simulation assumes the retry returns a service response whose
        # documented terminal receipt semantics were validated.
        if scenario.guarantees.receipt_semantics_documented:
            return Decision(
                OperationState.COMMITTED,
                "RETRY_SAME_KEY_CONFIRMED",
                effects,
                latency_ms,
                retry_safe=True,
                commit_from_retry=True,
            )
        return Decision(
            OperationState.UNKNOWN,
            "RETRY_SAME_KEY_OUTCOME_UNKNOWN",
            effects,
            latency_ms,
            retry_safe=True,
        )

    if proven_not_committed:
        return Decision(
            OperationState.COMMITTED,
            "RETRY_AFTER_FINAL_NONCOMMIT",
            1,
            latency_ms,
            retry_safe=True,
            commit_from_retry=True,
        )

    return Decision(
        OperationState.UNKNOWN,
        "DEFER_NO_SAFE_RETRY",
        int(scenario.original_commits),
        latency_ms,
    )


def _legacy_quorum(scenario: Scenario, now: datetime) -> Decision:
    observations = scenario.observations
    if not observations:
        return Decision(
            OperationState.UNKNOWN,
            "DEFER",
            int(scenario.original_commits),
            STATUS_LATENCY_MS,
        )

    legacy = tuple(
        Evidence(
            operation_id=PHASE2_OPERATION_ID,
            payload_hash=PHASE2_PAYLOAD_HASH,
            status=item.state.value,
            source=item.source_id,
            observed_at=now - timedelta(seconds=item.age_seconds),
            sequence=1,
            source_trusted=item.authenticated,
        )
        for item in observations
        if item.state in {OperationState.COMMITTED, OperationState.PROVEN_NOT_COMMITTED}
    )
    # Legacy Phase 2 recognized ABSENT, not a terminal no-commit state.
    normalized = tuple(
        Evidence(
            operation_id=item.operation_id,
            payload_hash=item.payload_hash,
            status=(
                "ABSENT"
                if item.status == OperationState.PROVEN_NOT_COMMITTED.value
                else item.status
            ),
            source=item.source,
            observed_at=item.observed_at,
            sequence=item.sequence,
            source_trusted=item.source_trusted,
        )
        for item in legacy
    )
    if not normalized:
        return Decision(
            OperationState.UNKNOWN,
            "DEFER",
            int(scenario.original_commits),
            STATUS_LATENCY_MS,
        )

    post = tuple(
        Evidence(
            operation_id=PHASE2_OPERATION_ID,
            payload_hash=PHASE2_PAYLOAD_HASH,
            status=(
                "ABSENT"
                if item.state == OperationState.PROVEN_NOT_COMMITTED
                else item.state.value
            ),
            source=item.source_id,
            observed_at=now - timedelta(seconds=item.age_seconds),
            sequence=1,
            source_trusted=item.authenticated,
        )
        for item in scenario.post_bound_observations
        if item.state in {OperationState.COMMITTED, OperationState.PROVEN_NOT_COMMITTED}
    )
    legacy_case = type(
        "LegacyCase",
        (),
        {
            "evidence": normalized,
            "retry_payload_matches": scenario.retry_payload_matches,
            "original_eventually_commits": scenario.original_commits,
            "idempotency_supported": scenario.guarantees.supports_idempotency,
            "elapsed_ms": scenario.elapsed_ms,
            "declared_max_duration_ms": scenario.duration_bound_ms,
            "post_settlement_evidence": post,
        },
    )()
    result = quorum_settlement_gate(legacy_case, now)
    state = (
        OperationState.COMMITTED
        if result.action == "CONFIRM_COMMITTED"
        else OperationState.UNKNOWN
    )
    effects = result.side_effect_count
    if result.action == "RETRY" and not scenario.retry_payload_matches:
        effects += 1
    return Decision(
        state,
        result.action,
        effects,
        result.latency_ms,
        payload_conflict=result.payload_conflict,
        retry_safe=(
            result.action == "RETRY"
            and scenario.retry_payload_matches
            and scenario.guarantees.safe_idempotent_retry
        ),
    )


def blind_retry(scenario: Scenario, now: datetime) -> Decision:
    del now
    return Decision(
        OperationState.UNKNOWN,
        "BLIND_RETRY",
        _side_effects_after_retry(scenario, deduplicated=False),
        100,
    )


def idempotency_only(scenario: Scenario, now: datetime) -> Decision:
    del now
    if scenario.guarantees.safe_idempotent_retry and scenario.retry_payload_matches:
        return _retry_decision(
            scenario,
            safe_idempotency=True,
            proven_not_committed=False,
            latency_ms=100,
        )
    if not scenario.retry_payload_matches:
        return _retry_decision(
            scenario,
            safe_idempotency=scenario.guarantees.safe_idempotent_retry,
            proven_not_committed=False,
            latency_ms=100,
        )
    return Decision(
        OperationState.UNKNOWN,
        "UNPROTECTED_RETRY",
        _side_effects_after_retry(scenario, deduplicated=False),
        100,
    )


def conservative_deferral(scenario: Scenario, now: datetime) -> Decision:
    del now
    state = classify_evidence(
        scenario.observations,
        scenario.guarantees,
    )
    if state == OperationState.COMMITTED:
        return Decision(state, "CONFIRM_VERIFIED_COMMIT", 1, STATUS_LATENCY_MS)
    if state == OperationState.PROVEN_NOT_COMMITTED:
        if scenario.guarantees.safe_idempotent_retry:
            return _retry_decision(
                scenario,
                safe_idempotency=True,
                proven_not_committed=True,
                latency_ms=STATUS_LATENCY_MS + RETRY_LATENCY_MS,
            )
        if scenario.guarantees.authoritative_status and scenario.guarantees.terminal_finality:
            return _retry_decision(
                scenario,
                safe_idempotency=False,
                proven_not_committed=True,
                latency_ms=STATUS_LATENCY_MS + RETRY_LATENCY_MS,
            )
    return Decision(
        state,
        "DEFER",
        int(scenario.original_commits),
        STATUS_LATENCY_MS,
    )


def guarantee_aware_controller(scenario: Scenario, now: datetime) -> Decision:
    del now
    state = classify_evidence(
        scenario.observations,
        scenario.guarantees,
    )
    if state == OperationState.COMMITTED:
        return Decision(state, "CONFIRM_VERIFIED_COMMIT", 1, STATUS_LATENCY_MS)

    if state == OperationState.PROVEN_NOT_COMMITTED:
        if scenario.guarantees.safe_idempotent_retry:
            return _retry_decision(
                scenario,
                safe_idempotency=True,
                proven_not_committed=True,
                latency_ms=STATUS_LATENCY_MS + RETRY_LATENCY_MS,
            )
        if scenario.guarantees.authoritative_status and scenario.guarantees.terminal_finality:
            return _retry_decision(
                scenario,
                safe_idempotency=False,
                proven_not_committed=True,
                latency_ms=STATUS_LATENCY_MS + RETRY_LATENCY_MS,
            )
        return Decision(state, "DEFER", int(scenario.original_commits), STATUS_LATENCY_MS)

    # A matching stable idempotency contract permits a same-payload retry even
    # without status; it does not convert a timeout into a confirmed outcome.
    if (
        scenario.guarantees.safe_idempotent_retry
        and scenario.retry_payload_matches
    ):
        return _retry_decision(
            scenario,
            safe_idempotency=True,
            proven_not_committed=False,
            latency_ms=RETRY_LATENCY_MS,
        )
    if (
        scenario.guarantees.safe_idempotent_retry
        and not scenario.retry_payload_matches
    ):
        return _retry_decision(
            scenario,
            safe_idempotency=True,
            proven_not_committed=False,
            latency_ms=RETRY_LATENCY_MS,
        )

    return Decision(
        state,
        "DEFER",
        int(scenario.original_commits),
        STATUS_LATENCY_MS if scenario.observations else 0,
    )


POLICIES: dict[str, Callable[[Scenario, datetime], Decision]] = {
    "blind_retry": blind_retry,
    "idempotency_only": idempotency_only,
    "conservative_deferral": conservative_deferral,
    "phase2_quorum_wait": _legacy_quorum,
    "guarantee_aware_controller": guarantee_aware_controller,
}


def _obs(
    state: OperationState,
    source_id: str,
    root: str,
    *,
    age: int = 0,
    authenticated: bool = True,
    authority: bool = False,
    terminal: bool = False,
    receipt: bool = False,
    operation_id: str = OPERATION_ID,
    payload_hash: str = PAYLOAD_HASH,
) -> Observation:
    return Observation(
        source_id,
        root,
        operation_id,
        payload_hash,
        state,
        age,
        authenticated,
        authority,
        terminal,
        receipt,
    )


def build_scenarios() -> tuple[Scenario, ...]:
    none = ServiceGuarantees()
    idem = ServiceGuarantees(
        supports_idempotency=True,
        idempotency_atomic_with_effect=True,
        receipt_semantics_documented=True,
    )
    idem_without_receipt = ServiceGuarantees(
        supports_idempotency=True,
        idempotency_atomic_with_effect=True,
    )
    non_atomic_idem = ServiceGuarantees(
        supports_idempotency=True,
        idempotency_atomic_with_effect=False,
        receipt_semantics_documented=True,
    )
    authoritative = ServiceGuarantees(
        authoritative_status=True,
        terminal_finality=True,
        receipt_semantics_documented=True,
    )
    primary = (
        _obs(
            OperationState.COMMITTED,
            "primary",
            "service-ledger",
            authority=True,
            terminal=True,
            receipt=True,
        ),
    )
    final_no_commit = (
        _obs(
            OperationState.PROVEN_NOT_COMMITTED,
            "primary",
            "service-ledger",
            authority=True,
            terminal=True,
        ),
    )
    return (
        Scenario("verified_commit_receipt", True, authoritative, primary),
        Scenario("authoritative_terminal_no_commit", False, authoritative, final_no_commit),
        Scenario(
            "shared_stale_cache_two_names",
            True,
            none,
            (
                _obs(OperationState.PROVEN_NOT_COMMITTED, "replica-1", "cache-cluster", age=1),
                _obs(OperationState.PROVEN_NOT_COMMITTED, "replica-2", "cache-cluster", age=1),
            ),
            elapsed_ms=1000,
            duration_bound_ms=1000,
        ),
        Scenario(
            "independent_observations_disagree",
            True,
            none,
            (
                _obs(OperationState.COMMITTED, "source-A", "ledger-A"),
                _obs(OperationState.PROVEN_NOT_COMMITTED, "source-B", "ledger-B"),
            ),
            independent_sources=True,
        ),
        Scenario(
            "primary_consistent_commit",
            True,
            authoritative,
            primary + (
                _obs(OperationState.PROVEN_NOT_COMMITTED, "replica", "lagging-replica"),
            ),
        ),
        Scenario(
            "cannot_establish_if_in_flight",
            True,
            none,
            (_obs(OperationState.UNKNOWN, "status", "eventual-cache"),),
        ),
        Scenario(
            "stale_status_response",
            True,
            authoritative,
            (
                _obs(
                    OperationState.PROVEN_NOT_COMMITTED,
                    "primary",
                    "service-ledger",
                    age=30,
                    authority=True,
                    terminal=True,
                ),
            ),
        ),
        Scenario(
            "commit_after_absence_snapshot",
            True,
            none,
            (
                _obs(OperationState.PROVEN_NOT_COMMITTED, "status-1", "replica-cache"),
                _obs(OperationState.PROVEN_NOT_COMMITTED, "status-2", "replica-cache"),
            ),
            elapsed_ms=1500,
            duration_bound_ms=1000,
            post_bound_observations=(
                _obs(OperationState.PROVEN_NOT_COMMITTED, "status-1", "replica-cache"),
                _obs(OperationState.PROVEN_NOT_COMMITTED, "status-2", "replica-cache"),
            ),
        ),
        Scenario(
            "mismatched_operation_or_payload",
            True,
            authoritative,
            (
                _obs(
                    OperationState.COMMITTED,
                    "primary",
                    "service-ledger",
                    authority=True,
                    terminal=True,
                    receipt=True,
                    operation_id="other-operation",
                ),
                _obs(
                    OperationState.PROVEN_NOT_COMMITTED,
                    "replica",
                    "replica",
                    payload_hash="other-hash",
                ),
            ),
        ),
        Scenario(
            "idempotency_without_status",
            True,
            idem,
            (),
        ),
        Scenario(
            "idempotency_without_verifiable_retry_receipt",
            True,
            idem_without_receipt,
            (),
        ),
        Scenario(
            "idempotency_not_atomic_with_effect",
            True,
            non_atomic_idem,
            (),
        ),
        Scenario(
            "neither_idempotency_nor_authoritative_status",
            False,
            none,
            (),
        ),
        Scenario(
            "changed_payload_same_key",
            True,
            idem,
            (),
            retry_payload_matches=False,
        ),
        Scenario(
            "false_independent_commit_agreement",
            False,
            none,
            (
                _obs(OperationState.COMMITTED, "source-A", "ledger-A"),
                _obs(OperationState.COMMITTED, "source-B", "ledger-B"),
            ),
        ),
    )


def evaluate(scenario: Scenario, decision: Decision) -> dict[str, int | str]:
    duplicate_count = (
        max(0, decision.side_effects - 1)
        if scenario.retry_payload_matches
        else 0
    )
    false_commit = int(
        decision.state == OperationState.COMMITTED
        and not scenario.original_commits
        and not decision.commit_from_retry
    )
    retry_issued = decision.action in {
        "BLIND_RETRY",
        "UNPROTECTED_RETRY",
        "RETRY",
        "RETRY_AFTER_FINAL_NONCOMMIT",
        "RETRY_SAME_KEY_CONFIRMED",
        "RETRY_SAME_KEY_OUTCOME_UNKNOWN",
    }
    unsafe_retry = int(retry_issued and not decision.retry_safe)
    correct_confirmation = int(
        (
            decision.state == OperationState.COMMITTED
            and (scenario.original_commits or decision.commit_from_retry)
            and not false_commit
        )
        or (
            decision.state == OperationState.PROVEN_NOT_COMMITTED
            and not scenario.original_commits
        )
    )
    resolved = int(
        decision.state
        in {OperationState.COMMITTED, OperationState.PROVEN_NOT_COMMITTED}
        and not false_commit
    )
    deferred = int(decision.action.startswith("DEFER"))
    return {
        "duplicate_side_effects": duplicate_count,
        "false_commit_confirmations": false_commit,
        "unsafe_retries": unsafe_retry,
        "correctly_confirmed_outcomes": correct_confirmation,
        "resolved_operations": resolved,
        "deferred_unresolved": int(not resolved),
        "deferred_actions": deferred,
        "modeled_latency_ms": decision.latency_ms,
        "action": decision.action,
    }


def run_comparison(repetitions: int = REPETITIONS):
    now = datetime.now(timezone.utc)
    scenarios = build_scenarios()
    results = {}
    for policy_name, policy in POLICIES.items():
        total: Counter[str] = Counter()
        per_scenario = {}
        for scenario in scenarios:
            scenario_total: Counter[str] = Counter()
            actions: Counter[str] = Counter()
            for _ in range(repetitions):
                evaluated = evaluate(scenario, policy(scenario, now))
                for metric, value in evaluated.items():
                    if isinstance(value, int):
                        total[metric] += value
                        scenario_total[metric] += value
                actions[evaluated["action"]] += 1
            per_scenario[scenario.name] = {
                **dict(scenario_total),
                "actions": dict(actions),
            }
        total["cases"] = len(scenarios) * repetitions
        results[policy_name] = {
            "totals": dict(total),
            "per_scenario": per_scenario,
        }
    return scenarios, results


def main():
    scenarios, results = run_comparison()
    print(
        f"Scenarios={len(scenarios)}, repetitions={REPETITIONS}, "
        f"cases_per_policy={len(scenarios) * REPETITIONS}"
    )
    print("Latency is a fixed modeled cost, not wall-clock measurement.")
    columns = (
        "duplicate_side_effects",
        "false_commit_confirmations",
        "unsafe_retries",
        "correctly_confirmed_outcomes",
        "resolved_operations",
        "deferred_unresolved",
        "deferred_actions",
        "modeled_latency_ms",
    )
    print("policy," + ",".join(columns) + ",mean_latency_ms")
    for name, result in results.items():
        totals = result["totals"]
        print(
            name + "," + ",".join(str(totals[col]) for col in columns)
            + f",{totals['modeled_latency_ms'] / totals['cases']:.1f}"
        )
    print("\nGuarantee-aware case outcomes:")
    for name, result in results["guarantee_aware_controller"]["per_scenario"].items():
        print(name, result["actions"])


if __name__ == "__main__":
    main()
