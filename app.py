import hashlib
import json
import math
import os
from pathlib import Path
import threading
import time

from flask import Flask, jsonify, render_template_string, request


app = Flask(__name__)
_lock = threading.Lock()
_submissions = []
_inflight_counts = {}
_idempotency_index = {}
_idempotency_inflight = {}

PAGE = """
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Local Recovery Experiment</title></head>
<body>
  <h1>Local Form Submission Test</h1>
  <p>This is a local-only mock application. It does not contact external services.</p>
  <label>Test operation ID <input id="operation_id" value="demo-001"></label>
  <button id="submit" onclick="submitOperation()">Submit operation</button>
  <p id="status">No confirmation received yet.</p>
  <script>
    async function submitOperation() {
      const operationId = document.getElementById("operation_id").value;
      document.getElementById("status").textContent = "Request sent; waiting for confirmation...";
      try {
        const response = await fetch("/submit?delay=2", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({operation_id: operationId})
        });
        const data = await response.json();
        document.getElementById("status").textContent = data.message;
      } catch (e) {
        document.getElementById("status").textContent = "Confirmation unavailable.";
      }
    }
  </script>
</body>
</html>
"""


def _request_hash(payload):
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bounded_delay(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default

    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc

    if not math.isfinite(value) or value < 0 or value > 5:
        raise ValueError(f"{name} must be between 0 and 5 seconds")
    return value


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.post("/submit")
def submit():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "invalid_json", "message": "Expected a JSON object."}), 400

    operation_id = payload.get("operation_id")
    if not isinstance(operation_id, str) or not operation_id.strip():
        return jsonify({
            "error": "invalid_operation_id",
            "message": "operation_id must be a non-empty string.",
        }), 400

    idempotency_key = request.headers.get("Idempotency-Key")
    if idempotency_key is not None:
        idempotency_key = idempotency_key.strip()
        if not idempotency_key:
            return jsonify({
                "error": "invalid_idempotency_key",
                "message": "Idempotency-Key must not be empty.",
            }), 400

    try:
        response_delay = _bounded_delay("delay", 2)
        commit_delay = _bounded_delay("commit_delay", 0)
    except ValueError as exc:
        return jsonify({"error": "invalid_delay", "message": str(exc)}), 400

    commit = request.args.get("commit", "1")
    if commit not in {"0", "1"}:
        return jsonify({
            "error": "invalid_commit",
            "message": "commit must be 0 or 1.",
        }), 400

    payload_hash = _request_hash(payload)
    owns_reservation = False

    with _lock:
        if idempotency_key:
            saved = _idempotency_index.get(idempotency_key)
            if saved is not None:
                if saved["request_hash"] != payload_hash:
                    return jsonify({
                        "error": "idempotency_key_payload_conflict",
                        "message": "This key was already used with a different payload.",
                    }), 409

                return jsonify({
                    "message": "Duplicate request; original operation reused.",
                    "operation_id": saved["operation_id"],
                    "duplicate": True,
                    "in_progress": False,
                })

            pending_hash = _idempotency_inflight.get(idempotency_key)
            if pending_hash is not None:
                if pending_hash != payload_hash:
                    return jsonify({
                        "error": "idempotency_key_payload_conflict",
                        "message": "This key is in use with a different payload.",
                    }), 409

                return jsonify({
                    "message": "Matching request is still in progress.",
                    "operation_id": operation_id,
                    "duplicate": True,
                    "in_progress": True,
                })

            _idempotency_inflight[idempotency_key] = payload_hash
            owns_reservation = True

        _inflight_counts[operation_id] = _inflight_counts.get(operation_id, 0) + 1

    try:
        test_hook = app.config.get("PRE_COMMIT_HOOK")
        if test_hook is not None:
            test_hook(operation_id)

        if commit_delay:
            time.sleep(commit_delay)

        with _lock:
            result = {
                "message": (
                    "Server confirmed."
                    if commit == "1"
                    else "Request completed without recording (simulation)."
                ),
                "operation_id": operation_id,
                "duplicate": False,
                "in_progress": False,
            }
            if commit == "1":
                record = {
                    "operation_id": operation_id,
                    "idempotency_key": idempotency_key,
                    "request_hash": payload_hash,
                    "recorded_at": time.time(),
                }
                _submissions.append(record)
                if idempotency_key:
                    _idempotency_index[idempotency_key] = {
                        "request_hash": payload_hash,
                        "operation_id": operation_id,
                    }
    finally:
        with _lock:
            if owns_reservation:
                _idempotency_inflight.pop(idempotency_key, None)
            active = _inflight_counts.get(operation_id, 0)
            if active <= 1:
                _inflight_counts.pop(operation_id, None)
            else:
                _inflight_counts[operation_id] = active - 1

    if response_delay:
        time.sleep(response_delay)
    return jsonify(result)


@app.get("/status")
def status():
    with _lock:
        items = list(_submissions)
    return jsonify({
        "total_submissions": len(items),
        "submissions": items,
        "observation": "snapshot_at_response_time_not_proof_of_future_non_commit",
    })


@app.post("/reset")
def reset():
    with _lock:
        if _inflight_counts:
            return jsonify({
                "error": "operations_in_flight",
                "message": "Cannot reset while submissions are in flight.",
            }), 409
        _submissions.clear()
        _idempotency_index.clear()
        _idempotency_inflight.clear()
    return jsonify({"ok": True})


@app.get("/test/inflight/<operation_id>")
def test_inflight(operation_id):
    """Local test probe; the server is intentionally bound to loopback only."""
    with _lock:
        return jsonify({
            "operation_id": operation_id,
            "in_flight": _inflight_counts.get(operation_id, 0) > 0,
            "recorded": any(
                item["operation_id"] == operation_id
                for item in _submissions
            ),
        })


if __name__ == "__main__":
    print(f"Application file: {Path(__file__).resolve()}")
    print("Registered routes:")
    for rule in app.url_map.iter_rules():
        print(f"  {rule}")
    port = int(os.environ.get("BROWSER_RECOVERY_PORT", "5055"))
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)
