
import json
import os
import time

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

BASE_URL = os.environ.get(
    "BROWSER_RECOVERY_BASE_URL", "http://127.0.0.1:5055"
)


def run_case(api, commit):
    # Reset the local mock server.
    reset = api.post(f"{BASE_URL}/reset")
    if not reset.ok:
        raise RuntimeError(f"Reset failed: HTTP {reset.status}")

    operation_id = f"case-{commit}"
    print(f"\nTesting commit={commit}")

    try:
        api.post(
            f"{BASE_URL}/submit?delay=2&commit={commit}",
            data=json.dumps({"operation_id": operation_id}),
            headers={"Content-Type": "application/json"},
            timeout=500,
        )
        observation = "Response received"

    except PlaywrightTimeoutError:
        observation = "TIMEOUT"

    print("Agent-visible observation:", observation)

    # Allow the server to finish processing.
    time.sleep(2.5)

    # Test-only inspection of the actual server state.
    status = api.get(f"{BASE_URL}/status")
    if not status.ok:
        raise RuntimeError(f"Status check failed: HTTP {status.status}")

    result = status.json()
    recorded = any(
        item["operation_id"] == operation_id
        for item in result["submissions"]
    )

    print("Actual operation recorded:", recorded)
    return observation, recorded


def main():
    with sync_playwright() as p:
        api = p.request.new_context()
        try:
            committed = run_case(api, 1)
            not_committed = run_case(api, 0)

            print("\n=== COMPARISON ===")
            print("Committed case:", committed)
            print("Non-committed case:", not_committed)
            print(
                "Same agent-visible observation:",
                committed[0] == not_committed[0],
            )
        finally:
            api.dispose()


if __name__ == "__main__":
    main()
