def recovery_decision(status, authoritative):
    if status == "COMMITTED" and authoritative:
        return "CONFIRMED_COMMITTED_NO_RETRY"

    if status == "ABSENT" and authoritative:
        return "OBSERVED_ABSENT_RETRY_WITH_SAME_KEY"

    return "UNKNOWN_DEFER_AND_RECONCILE"


tests = [
    ("committed authoritative", "COMMITTED", True),
    ("absent authoritative", "ABSENT", True),
    ("absent but stale", "ABSENT", False),
    ("status unavailable", "UNAVAILABLE", False),
    ("conflicting evidence", "CONFLICTING", False),
]

for name, status, authoritative in tests:
    decision = recovery_decision(status, authoritative)
    print(f"{name}: {decision}")

print(
    "An ABSENT result is only an observation at that time; it does not prove "
    "that an in-flight operation cannot later commit."
)
