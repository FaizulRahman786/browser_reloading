
import json
import os
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get(
    "BROWSER_RECOVERY_BASE_URL", "http://127.0.0.1:5055"
)
KEY = "conflict-test-001"


def main():
    with sync_playwright() as p:
        api = p.request.new_context()

        try:
            reset = api.post(f"{BASE_URL}/reset")
            if not reset.ok:
                raise RuntimeError(f"Reset failed: HTTP {reset.status}")

            headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": KEY,
            }

            requests = [
                {"operation_id": "operation-A"},
                {"operation_id": "operation-B"},
            ]

            for payload in requests:
                response = api.post(
                    f"{BASE_URL}/submit?delay=0.1&commit=1",
                    data=json.dumps(payload),
                    headers=headers,
                    timeout=3000,
                )

                print("\nPayload:", payload)
                print("HTTP status:", response.status)
                print("Response:", response.json())

            status = api.get(f"{BASE_URL}/status")
            print("\nFinal state:")
            print(json.dumps(status.json(), indent=2))

        finally:
            api.dispose()


if __name__ == "__main__":
    main()
