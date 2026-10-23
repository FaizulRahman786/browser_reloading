import json
import os
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get(
    "BROWSER_RECOVERY_BASE_URL", "http://127.0.0.1:5055"
)
operation_id = f"scenario5-{int(time.time())}"
idempotency_key = f"key-{operation_id}"

def request_json(url, method="GET", payload=None, timeout=0.3, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        url, data=data, headers=request_headers, method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.status, response.read().decode("utf-8")

print("=== Scenario 5: Unavailable status ===")
print("Operation ID:", operation_id)

try:
    code, body = request_json(
        f"{BASE_URL}/submit?delay=2&commit=1",
        method="POST",
        payload={"operation_id": operation_id},
        timeout=0.3,
        headers={"Idempotency-Key": idempotency_key},
    )
    print("Submission response:", code, body)
except (TimeoutError, urllib.error.URLError) as exc:
    print("Submission: TIMEOUT / CONNECTION ERROR")
    print("Details:", exc)

status_available = False
try:
    code, body = request_json(
        "http://127.0.0.1:5056/status", timeout=0.3
    )
    status_available = True
    print("Status response:", code, body)
except (TimeoutError, urllib.error.URLError) as exc:
    print("Status check: UNAVAILABLE")
    print("Details:", exc)

if not status_available:
    print("Agent decision: UNKNOWN - do not blindly retry")

# Researcher-only check after the agent's decision.
time.sleep(2.2)
try:
    _, body = request_json(f"{BASE_URL}/status", timeout=1)
    records = json.loads(body).get("submissions", [])
    recorded = any(
        item.get("operation_id") == operation_id for item in records
    )
    print("Later verification: operation recorded =", recorded)
except Exception as exc:
    print("Later verification failed:", exc)
