
import json
import time

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

BASE_URL = "http://127.0.0.1:5055"
OPERATION_ID = "recovery-demo-001"


def check_response(response, description):
    if not response.ok:
        raise RuntimeError(
            f"{description} failed with HTTP {response.status}"
        )


def get_server_status(page):
    """Read authoritative state from the local mock server."""
    response = page.request.get(f"{BASE_URL}/status")
    check_response(response, "Reading server status")
    return response.json()


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        try:
            # Reset the mock server for a clean experiment.
            reset = page.request.post(f"{BASE_URL}/reset")
            check_response(reset, "Resetting test server")

            page.goto(BASE_URL)
            page.locator("#operation_id").fill(OPERATION_ID)

            # Attempt the operation once.
            page.locator("#submit").click()

            try:
                page.wait_for_function(
                    "() => document.querySelector('#status')"
                    ".textContent.includes('Server confirmed')",
                    timeout=500,
                )
                print("Confirmation received.")

            except PlaywrightTimeoutError:
                print(
                    "Confirmation timed out. "
                    "Checking whether the action occurred..."
                )

                try:
                    status = get_server_status(page)
                    recorded_ids = [
                        item["operation_id"]
                        for item in status["submissions"]
                    ]

                    if OPERATION_ID in recorded_ids:
                        print("Operation found in server state.")
                        print("Skipping retry to prevent a duplicate.")
                    else:
                        print("Operation not found in current server state.")
                        print(
                            "Outcome remains uncertain; "
                            "no automatic retry."
                        )

                except Exception as exc:
                    print("Could not verify the operation:", str(exc))
                    print("Outcome remains unknown. No automatic retry.")

            # Allow the delayed response to finish.
            time.sleep(2.5)

            final_status = get_server_status(page)

            print("\nFinal server status:")
            print(json.dumps(final_status, indent=2))
            print(
                "Total recorded submissions:",
                final_status["total_submissions"],
            )

        finally:
            browser.close()


if __name__ == "__main__":
    main()
