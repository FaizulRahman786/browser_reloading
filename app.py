from flask import Flask, jsonify, request, render_template_string
import threading
import time

app = Flask(__name__)
_lock = threading.Lock()
_submissions = []

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

@app.get("/")
def index():
    return render_template_string(PAGE)


@app.post("/submit")
@app.post("/submit")
def submit():
    payload = request.get_json(silent=True) or {}
    operation_id = str(payload.get("operation_id", "unknown"))
    commit = request.args.get("commit", "1") == "1"
    idempotency_key = request.headers.get("Idempotency-Key")

    delay = min(
        max(request.args.get("delay", default=2, type=float), 0),
        5
    )

    with _lock:
        # A repeated key represents the same intended operation.
        existing = next(
            (
                item for item in _submissions
                if idempotency_key
                and item.get("idempotency_key") == idempotency_key
            ),
            None,
        )

        if existing:
            result = {
                "message": "Duplicate request detected; original result reused.",
                "operation_id": existing["operation_id"],
                "duplicate": True,
            }
        else:
            if commit:
                _submissions.append({
                    "operation_id": operation_id,
                    "idempotency_key": idempotency_key,
                    "recorded_at": time.time(),
                })

            result = {
                "message": "Request processed.",
                "operation_id": operation_id,
                "duplicate": False,
            }

    time.sleep(delay)
    return jsonify(result)

@app.get("/status")
def status():
    with _lock:
        items = list(_submissions)
    return jsonify({
        "total_submissions": len(items),
        "submissions": items
    })

@app.post("/reset")
def reset():
    with _lock:
        _submissions.clear()
    return jsonify({"ok": True})

if __name__ == "__main__":
    # Threaded server allows two delayed requests to overlap.
    app.run(host="127.0.0.1", port=5055, threaded=True, debug=False)
