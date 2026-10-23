
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from hashlib import sha256
import json


MAX_EVIDENCE_AGE_SECONDS = 10


@dataclass
class Evidence:
    operation_id: str
    payload_hash: str
    status: str
    source: str
    observed_at: datetime
    sequence: int
    source_trusted: bool


def hash_payload(payload):
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def validate_evidence(
    evidence,
    expected_operation_id,
    expected_payload_hash,
    now,
    max_age_seconds=MAX_EVIDENCE_AGE_SECONDS,
):
    reasons = []

    if evidence.operation_id != expected_operation_id:
        reasons.append("operation_id_mismatch")

    if evidence.payload_hash != expected_payload_hash:
        reasons.append("payload_hash_mismatch")

    if evidence.status not in {"COMMITTED", "ABSENT"}:
        reasons.append("unsupported_status")

    age = (now - evidence.observed_at).total_seconds()

    if age < 0:
        reasons.append("observation_time_in_future")

    if age > max_age_seconds:
        reasons.append("evidence_stale")

    if not evidence.source_trusted:
        reasons.append("source_not_trusted")

    if evidence.sequence < 0:
        reasons.append("invalid_sequence")

    return {
        "usable": len(reasons) == 0,
        "reasons": reasons,
        "age_seconds": age,
    }


def decide_recovery(evidence_items, operation_id, payload_hash, now):
    validations = [
        (
            evidence,
            validate_evidence(
                evidence,
                operation_id,
                payload_hash,
                now,
            ),
        )
        for evidence in evidence_items
    ]

    usable = [
        evidence
        for evidence, result in validations
        if result["usable"]
    ]

    # If no evidence passes validation, do not guess.
    if not usable:
        return "UNKNOWN_DEFER", validations

    # If trusted observations disagree, defer rather than guessing.
    statuses = {e.status for e in usable}
    if len(statuses) != 1:
        return "UNKNOWN_DEFER", validations

    # Different sources can have different sequence-number domains.
    # Therefore, do not compare sequence numbers across sources here.
    agreed_status = next(iter(statuses))

    if agreed_status == "COMMITTED":
        return "CONFIRMED_COMMITTED_NO_RETRY", validations

    return "OBSERVED_ABSENT_RETRY_WITH_SAME_KEY", validations


def make_evidence(
    operation_id,
    payload_hash,
    status,
    source,
    now,
    age_seconds=1,
    sequence=1,
    source_trusted=True,
):
    return Evidence(
        operation_id=operation_id,
        payload_hash=payload_hash,
        status=status,
        source=source,
        observed_at=now - timedelta(seconds=age_seconds),
        sequence=sequence,
        source_trusted=source_trusted,
    )


def run_case(name, evidence_items, operation_id, payload_hash, now):
    decision, validations = decide_recovery(
        evidence_items, operation_id, payload_hash, now
    )

    print(f"\nCASE: {name}")
    print(f"Decision: {decision}")
    if decision == "OBSERVED_ABSENT_RETRY_WITH_SAME_KEY":
        print("Meaning: no matching record was observed at observation time;")
        print("         this does not prove the operation cannot still commit.")

    for evidence, result in validations:
        print(
            f"  source={evidence.source}, "
            f"status={evidence.status}, "
            f"usable={result['usable']}, "
            f"reasons={result['reasons']}"
        )


def main():
    now = datetime.now(timezone.utc)
    operation_id = "booking-001"
    payload = {"date": "2026-11-01", "party_size": 2}
    payload_hash = hash_payload(payload)

    fresh_commit = make_evidence(
        operation_id, payload_hash, "COMMITTED",
        "mock_status_api", now, age_seconds=1, sequence=12
    )

    fresh_absent = make_evidence(
        operation_id, payload_hash, "ABSENT",
        "mock_status_api", now, age_seconds=1, sequence=13
    )

    stale_absent = make_evidence(
        operation_id, payload_hash, "ABSENT",
        "mock_status_api", now, age_seconds=30, sequence=10
    )

    wrong_payload = make_evidence(
        operation_id, "incorrect-hash", "COMMITTED",
        "mock_status_api", now
    )

    untrusted_commit = make_evidence(
        operation_id, payload_hash, "COMMITTED",
        "untrusted_source", now, source_trusted=False
    )

    conflicting_commit = make_evidence(
        operation_id, payload_hash, "COMMITTED",
        "source_a", now
    )

    conflicting_absent = make_evidence(
        operation_id, payload_hash, "ABSENT",
        "source_b", now
    )

    future_evidence = make_evidence(
        operation_id, payload_hash, "COMMITTED",
        "mock_status_api", now, age_seconds=-5
    )

    cases = [
        ("fresh committed evidence", [fresh_commit]),
        ("fresh absent evidence", [fresh_absent]),
        ("stale absence", [stale_absent]),
        ("wrong payload hash", [wrong_payload]),
        ("untrusted source", [untrusted_commit]),
        (
            "conflicting fresh sources",
            [conflicting_commit, conflicting_absent],
        ),
        ("future-dated evidence", [future_evidence]),
        ("no evidence", []),
    ]

    for name, items in cases:
        run_case(name, items, operation_id, payload_hash, now)

    print(
        "\nLimitations: source_trusted is an assumed Boolean label; "
        "sources are not independently authenticated, and timestamps or "
        "sequence values do not prove finality."
    )


if __name__ == "__main__":
    main()
