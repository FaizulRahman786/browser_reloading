# Outcome-Aware Recovery for Reliable AI Browser Automation

This local-only Flask prototype studies how an automation client should react when a browser operation times out or its outcome is ambiguous. It models submissions in memory; it does not contact websites or perform real bookings, payments, or account actions. The title is a research hypothesis, not a novelty or patentability claim.

## Requirements and setup

- Windows 10/11 and Python 3.10 or newer.
- Use the existing virtual environment when present:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

The Playwright browser download is needed only for browser-driven experiments. Installing dependencies or the browser may access package services; experiment runs themselves target the local mock server only.

## Architecture

- `app.py` provides a loopback-only Flask mock (`POST /submit`, `GET /status`, `POST /reset`) and the local `/test/inflight/<operation_id>` probe.
- Submissions are stored in process memory. An idempotency key maps to the canonical JSON payload hash: the same key and payload reuses the prior operation; a different payload gets HTTP 409. A same-key retry arriving while the original request is pre-commit receives an in-progress response and does not create a second record.
- `recovery.py` demonstrates a browser-driven timeout/status check.
- `scenario11_evidence_freshness.py` validates simulated evidence metadata and returns a conservative recovery decision.
- `tests/test_research.py` uses Flask's test client, Werkzeug's local server helper, and standard-library `unittest`. Scenario 12's pre-commit hook and events are deterministic test synchronization, not production coordination or a security feature.

`/status` is a snapshot at observation time. Seeing no record means only that no matching record appeared in that snapshot; it does not prove that a request still in flight cannot commit. The in-memory idempotency index, source-trust Boolean, timestamp checks, and test probe are not production-grade guarantees.

## Run the server

```powershell
.\.venv\Scripts\python.exe .\app.py
```

The app binds to `127.0.0.1:5055`. On startup it prints the resolved source path and registered route map. To use a different local port without disturbing an existing listener:

```powershell
$env:BROWSER_RECOVERY_PORT = "5057"
.\.venv\Scripts\python.exe .\app.py
```

For HTTP experiments against that server, set the matching URL in that PowerShell window:

```powershell
$env:BROWSER_RECOVERY_BASE_URL = "http://127.0.0.1:5057"
```

The default base URL remains `http://127.0.0.1:5055`.

## Tests and experiment commands

Run the isolated regression suite (no server process required):

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run the synchronized race experiment (in process; no server process required):

```powershell
.\.venv\Scripts\python.exe .\scenario12_inflight_race.py
```

The race script waits for the original request's pre-commit hook, checks the in-flight probe and zero records, sends the retry, releases the original request, joins both requests, and asserts the final record count.

With the local server running, these scripts exercise HTTP/browser behavior:

```powershell
.\.venv\Scripts\python.exe .\baseline.py
.\.venv\Scripts\python.exe .\ambiguity_experiment.py
.\.venv\Scripts\python.exe .\idempotency_experiment.py
.\.venv\Scripts\python.exe .\idempotency_conflict_test.py
.\.venv\Scripts\python.exe .\scenario5_unavailable_status.py
.\.venv\Scripts\python.exe .\scenario6_retry_comparison.py
.\.venv\Scripts\python.exe .\scenario7_repeatability.py
.\.venv\Scripts\python.exe .\scenario8_reconciliation.py
.\.venv\Scripts\python.exe .\recovery.py
```

Synthetic rule-based experiments do not need a server:

```powershell
.\.venv\Scripts\python.exe .\scenario9_evidence_policy.py
.\.venv\Scripts\python.exe .\scenario10_hidden_outcome_benchmark.py
.\.venv\Scripts\python.exe .\scenario11_evidence_freshness.py
.\.venv\Scripts\python.exe .\recovery_policy_benchmark.py
```

## Troubleshooting

- **Port 5055 is occupied:** identify the listener before taking action:

  ```powershell
  Get-NetTCPConnection -LocalPort 5055 -State Listen |
    ForEach-Object { Get-CimInstance Win32_Process -Filter "ProcessId = $($_.OwningProcess)" }
  ```

  Confirm its executable, command line, and working directory before deciding whether it is safe to stop. Do not terminate an unidentified process. Use `BROWSER_RECOVERY_PORT` and `BROWSER_RECOVERY_BASE_URL` to run an isolated instance instead.
- **Scenario 12 returns 404:** its in-process test requires no port. For a server route check, inspect the printed route map and resolved application path, then compare them with the live listener. A source file may contain the endpoint while a different or earlier Flask app instance is still serving the port.
- **Playwright cannot start Chromium:** run the install command above in the existing virtual environment. Browser experiments use headless mode.
- **Unavailable status:** Scenario 5 deliberately queries a separate, normally unserved local port. This is a simulation of missing status evidence; the correct agent-side conclusion is unresolved, not failed.

## Research interpretation and limitations

- Browser/server runs are observations of this mock, not external reliability measurements.
- Scenarios 9–11 and the recovery-policy benchmark are deterministic rule checks over synthetic inputs. Their cases are not independent real-world experiments.
- `ABSENT` is not proof of finality. A retry after an absence observation is only the prototype's policy; in practice it is safe only if the target operation has suitable idempotency semantics.
- `source_trusted` is an assumed label, not source authentication. Timestamps are metadata, and the `sequence` field does not prove freshness, ordering, or finality.
- The prototype has no durable storage, multi-process consistency, authenticated receipts, transactional boundary, or production security controls.
- No novelty, patentability, production readiness, statistical significance, or real-world reliability improvement has been established. See [FINAL_RESEARCH_REPORT.md](./FINAL_RESEARCH_REPORT.md).
