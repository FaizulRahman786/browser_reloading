from collections import Counter

TRIALS = 100

def simulate(policy, committed):
    # The agent observes a timeout in both cases.
    # It cannot observe the hidden committed value directly.
    if policy == "blind_retry":
        return {
            "duplicate_risk": committed,
            "incomplete_risk": not committed,
            "decision": "retry",
        }

    if policy == "never_retry":
        return {
            "duplicate_risk": False,
            "incomplete_risk": not committed,
            "decision": "stop",
        }

    if policy == "defer_reconcile":
        # No retry while the outcome is unknown.
        # Reconciliation is pending; no claim of completion is made.
        return {
            "duplicate_risk": False,
            "incomplete_risk": False,
            "decision": "pending_reconciliation",
        }

    raise ValueError("Unknown policy")


def run_benchmark():
    policies = ["blind_retry", "never_retry", "defer_reconcile"]

    for policy in policies:
        metrics = Counter()

        for _ in range(TRIALS):
            for committed in (True, False):
                result = simulate(policy, committed)
                metrics["cases"] += 1
                metrics["duplicate_risk_cases"] += result["duplicate_risk"]
                metrics["incomplete_risk_cases"] += result["incomplete_risk"]
                metrics[result["decision"]] += 1

        print(f"\nPolicy: {policy}")
        print("Cases:", metrics["cases"])
        print("Duplicate-risk cases:", metrics["duplicate_risk_cases"])
        print("Incomplete-risk cases:", metrics["incomplete_risk_cases"])
        print("Decisions:", {
            key: metrics[key]
            for key in (
                "retry", "stop", "pending_reconciliation"
            )
        })


if __name__ == "__main__":
    run_benchmark()
