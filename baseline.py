import json
import time
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "http://127.0.0.1:5055"

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto(BASE_URL)

        # Start the first action. The server records it immediately, but waits
        # 2 seconds before returning the confirmation.
        page.locator("#submit").click()
        try:
            page.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('Server confirmed')",
                timeout=500
            )
            first_result = "confirmation received"
        except PlaywrightTimeoutError:
            first_result = "TIMEOUT: outcome is ambiguous"

        print("First attempt:", first_result)

        # Naive baseline behavior: retry after timeout without reconciling
        # whether the first operation already happened.
        page.locator("#submit").click()
        try:
            page.wait_for_function(
                "() => document.querySelector('#status').textContent.includes('Server confirmed')",
                timeout=500
            )
            second_result = "confirmation received"
        except PlaywrightTimeoutError:
            second_result = "TIMEOUT: outcome is ambiguous"

        print("Second attempt:", second_result)

        # Let both delayed server responses finish, then inspect ground truth.
        time.sleep(2.5)
        response = page.request.get(f"{BASE_URL}/status")
        result = response.json()
        print("Ground-truth server status:")
        print(json.dumps(result, indent=2))
        print("\nInterpretation:")
        print(f"  Submissions recorded: {result['total_submissions']}")
        if result["total_submissions"] > 1:
            print("  The naive retry caused duplicate side effects in this mock test.")
        else:
            print("  No duplicate side effect observed in this run.")

        browser.close()

if __name__ == "__main__":
    main()
