import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get(
    "BROWSER_RECOVERY_BASE_URL", "http://127.0.0.1:5055"
)

def request_json(path, method="GET", payload=None, timeout=0.3, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(
        BASE + path, data=data, headers=request_headers, method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def attempt(operation_id, key=None):
    headers = {}
    if key is not None:
        headers["Idempotency-Key"] = key

    try:
        result = request_json(
            "/submit?delay=2&commit=1",
            method="POST",
            payload={"operation_id": operation_id},
            timeout=0.3,
            headers=headers,
        )
        print("Response:", result)
    except (TimeoutError, urllib.error.URLError) as exc:
        print("Client observed timeout:", str(exc))

def reset():
    request_json("/reset", method="POST", timeout=2)

def count_for(operation_id):
    data = request_json("/status", timeout=3)
    return sum(
        item.get("operation_id") == operation_id
        for item in data.get("submissions", [])
    )

print("=== Strategy A: blind retry ===")
reset()
op_a = f"blind-{int(time.time())}"
attempt(op_a)
attempt(op_a)
time.sleep(2.3)
print("Recorded operations for Strategy A:", count_for(op_a))

print("\n=== Strategy B: retry with same idempotency key ===")
reset()
op_b = f"protected-{int(time.time())}"
key_b = f"stable-{op_b}"
attempt(op_b, key_b)
attempt(op_b, key_b)
time.sleep(2.3)
print("Recorded operations for Strategy B:", count_for(op_b))
