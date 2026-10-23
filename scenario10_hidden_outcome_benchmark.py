from collections import Counter

TRIALS_PER_CASE = 100

# The agent sees evidence, not the hidden true outcome.
CASES = [
    ("committed_fresh", True, "COMMITTED", True),
    ("absent_fresh", False, "ABSENT", True),
    ("committed_but_stale_absence", True, "ABSENT", False),
    ("absent_but_stale_commit", False, "COMMITTED", False),
    ("status_unavailable", True, "UNAVAILABLE", False),
    ("conflicting_evidence", False, "CONFLICTING", False),
]

def recovery_decision(status, authoritative):
    if status == "COMMITTED" and authoritative:
        return "CONFIRMED_COMMITTED_NO_RETRY"
    if status == "ABSENT" and authoritative:
        return "OBSERVED_ABSENT_RETRY_WITH_SAME_KEY"
    return "UNKNOWN_DEFER"

def evaluate(true_committed, decision):
    # Conservative evaluation:
    # a deferred result is safe but unresolved.
    if decision == "CONFIRMED_COMMITTED_NO_RETRY":
        return "correct" if true_committed else "false_commit"
    if decision == "OBSERVED_ABSENT_RETRY_WITH_SAME_KEY":
        return "correct" if not true_committed else "unsafe_retry"
    return "pending"

totals = Counter()

for name, true_committed, evidence, authoritative in CASES:
    case_counts = Counter()

    for _ in range(TRIALS_PER_CASE):
        decision = recovery_decision(evidence, authoritative)
        result = evaluate(true_committed, decision)
        case_counts[result] += 1
        totals[result] += 1

    print(f"\nCase: {name}")
    print("  True outcome:", "COMMITTED" if true_committed else "ABSENT")
    print("  Evidence:", evidence, "| authoritative:", authoritative)
    print("  Decision:", recovery_decision(evidence, authoritative))
    print("  Evaluation:", dict(case_counts))

print("\n=== Overall results ===")
print("Cases:", sum(totals.values()))
print("Correct resolved decisions:", totals["correct"])
print("False commit decisions:", totals["false_commit"])
print("Unsafe retry decisions:", totals["unsafe_retry"])
print("Pending reconciliation:", totals["pending"])
