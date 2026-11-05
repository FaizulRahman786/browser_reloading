"""Deterministic, local-only comparison of Phase 2 recovery policies."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable

from scenario11_evidence_freshness import validate_evidence
from scenario11_evidence_freshness import Evidence


SIMULATED_RETRY_LATENCY_MS = 100
SIMULATED_STATUS_LATENCY_MS = 50
SIMULATED_QUORUM = 2
TRIALS_PER_SCENARIO = 20
EXPECTED_OPERATION_ID = "phase2-op"
EXPECTED_PAYLOAD_HASH = "payload-A"


@dataclass(frozen=True)
class RecoveryCase:
    name: str
    original_eventually_commits: bool
    idempotency_supported: bool
    evidence: tuple[Evidence, ...]
    retry_payload_matches: bool = True
    elapsed_ms: int = 0
    declared_max_duration_ms: int = 1000
    post_settlement_evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class PolicyResult:
    action: str
    side_effect_count: int
    latency_ms: int
    payload_conflict: bool = False


def _usable_evidence(case: RecoveryCase, now, evidence_items=None, at_time=None):
    observations = case.evidence if evidence_items is None else evidence_items
    validation_time = now if at_time is None else at_time
    return [
        evidence
        for evidence in observations
        if validate_evidence(
            evidence,
            EXPECTED_OPERATION_ID,
            EXPECTED_PAYLOAD_HASH,
            validation_time,
        )["usable"]
    ]


def _retry_result(
    case: RecoveryCase,
    *,
    use_idempotency: bool,
    latency_ms: int,
) -> PolicyResult:
    if not case.retry_payload_matches and use_idempotency:
        return PolicyResult(
            "RETRY_REJECTED_CONFLICT",
            int(case.original_eventually_commits),
            latency_ms,
            payload_conflict=True,
        )

    if case.idempotency_supported and use_idempotency and case.retry_payload_matches:
        count = 1
    else:
        count = int(case.original_eventually_commits) + 1

    return PolicyResult("RETRY", count, latency_ms)


def blind_retry(case: RecoveryCase, now) -> PolicyResult:
    del now
    return _retry_result(
        case,
        use_idempotency=False,
        latency_ms=SIMULATED_RETRY_LATENCY_MS,
    )


def idempotency_only(case: RecoveryCase, now) -> PolicyResult:
    del now
    return _retry_result(
        case,
        use_idempotency=True,
        latency_ms=SIMULATED_RETRY_LATENCY_MS,
    )


def evidence_deferral(case: RecoveryCase, now) -> PolicyResult:
    usable = _usable_evidence(case, now)
    observation_latency = SIMULATED_STATUS_LATENCY_MS
    if not usable:
        return PolicyResult("DEFER", int(case.original_eventually_commits), observation_latency)

    statuses = {evidence.status for evidence in usable}
    if len(statuses) != 1:
        return PolicyResult(
            "DEFER",
            int(case.original_eventually_commits),
            observation_latency,
        )

    status = next(iter(statuses))
    if status == "COMMITTED":
        return PolicyResult(
            "CONFIRM_COMMITTED",
            int(case.original_eventually_commits),
            observation_latency,
        )

    if not case.retry_payload_matches:
        return PolicyResult(
            "DEFER_PAYLOAD_MISMATCH",
            int(case.original_eventually_commits),
            observation_latency,
        )

    retried = _retry_result(
        case,
        use_idempotency=True,
        latency_ms=observation_latency + SIMULATED_RETRY_LATENCY_MS,
    )
    return retried


def quorum_settlement_gate(case: RecoveryCase, now) -> PolicyResult:
    """Require two fresh source votes; wait out the declared absence horizon."""
    usable = _usable_evidence(case, now)
    latency = SIMULATED_STATUS_LATENCY_MS
    if not case.retry_payload_matches:
        return PolicyResult(
            "DEFER_PAYLOAD_MISMATCH",
            int(case.original_eventually_commits),
            latency,
        )

    votes_by_status: Counter[str] = Counter()
    sources_by_status: dict[str, set[str]] = {}
    for evidence in usable:
        sources = sources_by_status.setdefault(evidence.status, set())
        sources.add(evidence.source)
        votes_by_status[evidence.status] = len(sources)

    qualifying = [
        status
        for status, count in votes_by_status.items()
        if count >= SIMULATED_QUORUM
    ]
    if len(qualifying) != 1:
        return PolicyResult(
            "DEFER",
            int(case.original_eventually_commits),
            latency,
        )

    status = qualifying[0]
    if status == "COMMITTED":
        return PolicyResult(
            "CONFIRM_COMMITTED",
            int(case.original_eventually_commits),
            latency,
        )

    remaining_horizon = max(
        0,
        case.declared_max_duration_ms - case.elapsed_ms,
    )
    latency += remaining_horizon
    if remaining_horizon:
        settled_evidence = _usable_evidence(
            case,
            now,
            case.post_settlement_evidence,
            at_time=now + timedelta(milliseconds=remaining_horizon),
        )
        settled_absence_sources = {
            evidence.source
            for evidence in settled_evidence
            if evidence.status == "ABSENT"
        }
        latency += SIMULATED_STATUS_LATENCY_MS
        if len(settled_absence_sources) < SIMULATED_QUORUM:
            return PolicyResult(
                "DEFER_SETTLEMENT_WINDOW",
                int(case.original_eventually_commits),
                latency,
            )

    retried = _retry_result(
        case,
        use_idempotency=True,
        latency_ms=latency + SIMULATED_RETRY_LATENCY_MS,
    )
    return retried


POLICIES = {
    "blind_retry": blind_retry,
    "idempotency_only": idempotency_only,
    "evidence_deferral": evidence_deferral,
    "quorum_settlement_gate": quorum_settlement_gate,
}


def build_cases(now) -> tuple[RecoveryCase, ...]:
    operation_id = "phase2-op"
    payload_hash = EXPECTED_PAYLOAD_HASH

    def observation(
        source: str,
        status: str,
        *,
        age_seconds: int = 1,
        after_seconds: int = 0,
        trusted: bool = True,
        hash_value: str = payload_hash,
    ) -> Evidence:
        return Evidence(
            operation_id=operation_id,
            payload_hash=hash_value,
            status=status,
            source=source,
            observed_at=now + timedelta(
                seconds=after_seconds - age_seconds
            ),
            sequence=1,
            source_trusted=trusted,
        )

    return (
        RecoveryCase(
            "fresh_commit_consensus",
            True,
            True,
            (
                observation("source-A", "COMMITTED"),
                observation("source-B", "COMMITTED"),
                observation("source-C", "COMMITTED"),
            ),
        ),
        RecoveryCase(
            "settled_absence_consensus",
            False,
            False,
            (
                observation("source-A", "ABSENT"),
                observation("source-B", "ABSENT"),
                observation("source-C", "ABSENT"),
            ),
            elapsed_ms=0,
            post_settlement_evidence=(
                observation("source-A", "ABSENT", after_seconds=1),
                observation("source-B", "ABSENT", after_seconds=1),
                observation("source-C", "ABSENT", after_seconds=1),
            ),
        ),
        RecoveryCase(
            "late_commit_after_absence_and_declared_bound",
            True,
            False,
            (
                observation("source-A", "ABSENT"),
                observation("source-B", "ABSENT"),
                observation("source-C", "ABSENT"),
            ),
            elapsed_ms=1500,
            declared_max_duration_ms=1000,
        ),
        RecoveryCase(
            "stale_absence_with_fresh_commit_quorum",
            True,
            True,
            (
                observation("source-A", "ABSENT", age_seconds=30),
                observation("source-B", "COMMITTED"),
                observation("source-C", "COMMITTED"),
            ),
        ),
        RecoveryCase(
            "fresh_two_to_one_conflict",
            True,
            False,
            (
                observation("source-A", "COMMITTED"),
                observation("source-B", "COMMITTED"),
                observation("source-C", "ABSENT"),
            ),
        ),
        RecoveryCase(
            "false_commit_quorum",
            False,
            False,
            (
                observation("source-A", "COMMITTED"),
                observation("source-B", "COMMITTED"),
                observation("source-C", "ABSENT"),
            ),
        ),
        RecoveryCase(
            "changed_retry_payload",
            True,
            True,
            (
                observation("source-A", "ABSENT"),
                observation("source-B", "ABSENT"),
            ),
            retry_payload_matches=False,
            elapsed_ms=1500,
        ),
        RecoveryCase(
            "no_status_and_no_remote_idempotency",
            True,
            False,
            (),
        ),
        RecoveryCase(
            "single_inconsistent_absence_source",
            True,
            False,
            (observation("stale-replica", "ABSENT"),),
        ),
        RecoveryCase(
            "untrusted_agreeing_sources",
            False,
            False,
            (
                observation("source-A", "ABSENT", trusted=False),
                observation("source-B", "ABSENT", trusted=False),
            ),
            elapsed_ms=1500,
        ),
    )


def evaluate_case(case: RecoveryCase, result: PolicyResult) -> dict[str, int | bool | str]:
    original_committed = case.original_eventually_commits
    duplicate_count = max(0, result.side_effect_count - 1)
    incorrect_confirmation = (
        result.action == "CONFIRM_COMMITTED" and not original_committed
    )
    retry_attempted = result.action in {"RETRY", "RETRY_REJECTED_CONFLICT"}
    unsafe_retry = (
        retry_attempted
        and original_committed
        and result.side_effect_count > 1
    )

    successfully_resolved = (
        result.action == "CONFIRM_COMMITTED" and original_committed
    ) or (
        result.action == "RETRY"
        and case.retry_payload_matches
        and result.side_effect_count == 1
    )
    deferred = result.action.startswith("DEFER")
    unresolved = not successfully_resolved
    return {
        "duplicate_operations": duplicate_count,
        "incorrectly_confirmed_commits": int(incorrect_confirmation),
        "unsafe_retries": int(unsafe_retry),
        "successfully_resolved": int(successfully_resolved),
        "deferred": int(deferred),
        "unresolved": int(unresolved),
        "payload_conflicts": int(result.payload_conflict),
        "latency_ms": result.latency_ms,
        "action": result.action,
    }


def run_benchmark(cases: Iterable[RecoveryCase], trials: int = TRIALS_PER_SCENARIO):
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    cases = tuple(cases)
    results = {}
    for policy_name, policy in POLICIES.items():
        totals: Counter[str] = Counter()
        per_case = {}
        for case in cases:
            case_totals: Counter[str] = Counter()
            action_counts: Counter[str] = Counter()
            for _ in range(trials):
                evaluated = evaluate_case(case, policy(case, now))
                for metric, value in evaluated.items():
                    if isinstance(value, int):
                        totals[metric] += value
                        case_totals[metric] += value
                action_counts[evaluated["action"]] += 1
            per_case[case.name] = {
                **dict(case_totals),
                "actions": dict(action_counts),
            }
        totals["cases"] = len(cases) * trials
        results[policy_name] = {
            "totals": dict(totals),
            "per_case": per_case,
        }
    return results


def main():
    from datetime import datetime, timezone

    cases = build_cases(datetime.now(timezone.utc))
    results = run_benchmark(cases)
    print("Phase 2 synthetic policy comparison")
    print(
        f"Scenarios={len(cases)}, repetitions per scenario={TRIALS_PER_SCENARIO}, "
        f"cases per policy={len(cases) * TRIALS_PER_SCENARIO}"
    )
    print(
        "Latency values are modeled costs in milliseconds, not wall-clock "
        "measurements."
    )
    columns = (
        "duplicate_operations",
        "incorrectly_confirmed_commits",
        "unsafe_retries",
        "successfully_resolved",
        "deferred",
        "unresolved",
        "payload_conflicts",
        "latency_ms",
    )
    print("policy," + ",".join(columns) + ",mean_latency_ms")
    for policy_name, result in results.items():
        totals = result["totals"]
        mean_latency = totals["latency_ms"] / totals["cases"]
        print(
            policy_name
            + ","
            + ",".join(str(totals[column]) for column in columns)
            + f",{mean_latency:.1f}"
        )

    print("\nCandidate case outcomes:")
    for case_name, data in results["quorum_settlement_gate"]["per_case"].items():
        print(case_name, data["actions"])


if __name__ == "__main__":
    main()
