import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get(
    "BROWSER_RECOVERY_BASE_URL", "http://127.0.0.1:5055"
)

def call(path, method="GET", payload=None, timeout=0.3, headers=None):
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    h = dict(headers or {})
    if data is not None:
        h["Content-Type"] = "application/json"

    req = urllib.request.Request(
        BASE + path, data=data, headers=h, method=method
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))

def submit(op, key, commit):
    try:
        result = call(
            f"/submit?delay=2&commit={commit}",
            method="POST",
            payload={"operation_id": op},
            timeout=0.3,
            headers={"Idempotency-Key": key},
        )
        print("Submission response:", result)
    except (TimeoutError, urllib.error.URLError):
        print("Submission timed out; outcome = UNKNOWN")

def is_recorded(op):
    state = call("/status", timeout=3)
    return any(
        item.get("operation_id") == op
        for item in state.get("submissions", [])
    )

def run_case(commit):
    call("/reset", method="POST", timeout=3)
    op = f"reconcile-{commit}-{int(time.time() * 1000)}"
    key = f"stable-{op}"

    print(f"\n=== Original commit setting: {commit} ===")
    submit(op, key, commit)

    # Simulate the status service being temporarily unavailable.
    try:
        urllib.request.urlopen(
            "http://127.0.0.1:5056/status", timeout=0.3
        )
        print("Unexpected: simulated unavailable service responded")
    except (TimeoutError, urllib.error.URLError):
        print("Status unavailable: defer; do not blindly retry")

    # Wait for the delayed server request to finish, then reconcile.
    time.sleep(2.2)
    recorded = is_recorded(op)
    print("Mock state at observation time says recorded:", recorded)

    if recorded:
        print("Decision: CONFIRMED_COMMITTED; do not retry")
    else:
        print(
            "Decision: no record observed in this mock at this time; "
            "retry once with the same idempotency key"
        )
        result = call(
            "/submit?delay=0&commit=1",
            method="POST",
            payload={"operation_id": op},
            timeout=3,
            headers={"Idempotency-Key": key},
        )
        print("Retry response:", result)
        print("Recorded after retry:", is_recorded(op))

if __name__ == "__main__":
    run_case(commit=1)
    run_case(commit=0)
