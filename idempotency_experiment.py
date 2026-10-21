
import json
import time

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

BASE_URL = "http://127.0.0.1:5055"


def main():
    with sync_playwright() as p:
        api = p.request.new_context()

        try:
            reset = api.post(f"{BASE_URL}/reset")
            if not reset.ok:
                raise RuntimeError(f"Reset failed: HTTP {reset.status}")

            operation_id = "idem-demo-001"
            key = "stable-key-001"

            headers = {
                "Content-Type": "application/json",
                "Idempotency-Key": key,
            }
            body = json.dumps({"operation_id": operation_id})

            for attempt in range(1, 3):
                print(f"\nAttempt {attempt}")

                try:
                    response = api.post(
                        f"{BASE_URL}/submit?delay=2&commit=1",
                        data=body,
                        headers=headers,
                        timeout=500,
                    )
                    print("Response:", response.json())

                except PlaywrightTimeoutError:
                    print("Client timed out; outcome is unknown.")

            # Wait for both server requests to finish.
            time.sleep(2.5)

            status = api.get(f"{BASE_URL}/status")
            if not status.ok:
                raise RuntimeError(
                    f"Status failed: HTTP {status.status}"
                )

            result = status.json()
            print("\nFinal server state:")
            print(json.dumps(result, indent=2))
            print("Total recorded operations:", result["total_submissions"])

        finally:
            api.dispose()


if __name__ == "__main__":
    main()
