import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get(
    "BROWSER_RECOVERY_BASE_URL", "http://127.0.0.1:5055"
)
TRIALS = 20

def call(path, method="GET", payload=None, timeout=0.04, headers=None):
    data = None if payload is None else json.dumps(payload).encode()
    h = dict(headers or {})
    if data is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode())

def attempt(op, key=None):
    headers = {"Idempotency-Key": key} if key else {}
    try:
        call("/submit?delay=0.15&commit=1", "POST",
             {"operation_id": op}, timeout=0.04, headers=headers)
    except (TimeoutError, urllib.error.URLError):
        pass

def count(op):
    state = call("/status", timeout=3)
    return sum(x.get("operation_id") == op for x in state["submissions"])

def reset():
    call("/reset", "POST", timeout=3)

def run_trial(protected, i):
    op = f"trial-{int(time.time() * 1000)}-{i}"
    key = f"key-{op}" if protected else None
    attempt(op, key)
    attempt(op, key)
    time.sleep(0.25)
    return count(op)

for protected in (False, True):
    reset()
    counts = [run_trial(protected, i) for i in range(TRIALS)]
    duplicates = sum(n > 1 for n in counts)
    missing = sum(n == 0 for n in counts)
    print("\nStrategy:", "Idempotency protected" if protected else "Blind retry")
    print("Trials:", TRIALS)
    print("Trials with duplicate records:", duplicates)
    print("Trials with no recorded operation:", missing)
    print("Total records:", sum(counts))
