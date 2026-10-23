# Final Research Report

**Working title:** Outcome-Aware Recovery for Reliable AI Browser Automation  
**Report date:** 2026-10-23  
**Project:** Local Flask research prototype  
**Overall status:** Prototype/regression suite PASS; production readiness, novelty, patentability, and real-world reliability improvement NOT ESTABLISHED.

## 1. Executive summary

The project now has an isolated Flask mock, a corrected idempotency path for concurrent same-key submissions, reset/in-flight protection, input validation, and standard-library regression tests. The earlier Scenario 12 observation was not a valid race result: the request had already been recorded before the retry. Scenario 12 now synchronizes on a pre-commit test hook, proves zero records before retry, waits for both requests, and asserts the final state.

Measured in this mock:

- Scenario 12 produced **2 records without a key** and **1 with the same key and payload**, with **0 records before either retry**.
- Scenario 7 reproduced **20/20 duplicate trials** for blind retry and **0/20** for idempotency-protected retry.
- The 19 regression tests passed.
- Synthetic benchmarks reproduced their expected deterministic counts; these are not real-world trials.

The port-5055 failure came from the already-running listener, not the current source imported in the workspace. That listener returned 404 for the in-flight route and an older `/status` response shape. Its process command line referenced `.\app.py` under the project virtual-environment executable, but its current directory was unavailable through the process query. It could not be proven whether the process had loaded stale code or launched from a different working directory. It was left untouched. The updated server was started and tested on port 5057.

The implementation is an in-memory mock. Its idempotency behavior is not durable, cross-process, or production-safe. No patentability conclusion is supported. Further technical differentiation and a deeper prior-art review are needed before treating this as a filing candidate.

## 2. Research question

When a browser automation client times out after initiating a state-changing action, what evidence and recovery policy can reduce duplicate actions without incorrectly treating uncertainty or an absence observation as proof of failure?

This prototype compares blind retry, same-key idempotent retry, no retry, and defer/reconcile policies in controlled simulations.

## 3. Problem definition

A client timeout is an observation about the client/server exchange, not a definitive statement about the remote side effect. The request may not have arrived, may still be in progress, may have committed while its response was lost, or may have failed before committing. Retrying without a suitable idempotency contract can duplicate side effects. Conversely, never retrying can leave work incomplete.

The prototype makes this ambiguity observable with a local mock operation. A `/status` snapshot only says what appeared in the in-memory record list at the time of that observation. In particular, zero records while an operation is in flight is **not proof that it cannot later commit**.

## 4. Prototype architecture

- [`app.py`](./app.py) — local Flask app, JSON validation, bounded response/pre-commit delays, in-memory submission and idempotency state, reset endpoint, and local test probe.
- [`recovery.py`](./recovery.py) — browser-driven timeout and status-check demonstration.
- [`baseline.py`](./baseline.py), [`ambiguity_experiment.py`](./ambiguity_experiment.py), and [`idempotency_experiment.py`](./idempotency_experiment.py) — browser-oriented mock experiments.
- [`scenario5_unavailable_status.py`](./scenario5_unavailable_status.py) through [`scenario12_inflight_race.py`](./scenario12_inflight_race.py) — scenario-specific experiments.
- [`scenario11_evidence_freshness.py`](./scenario11_evidence_freshness.py), [`scenario10_hidden_outcome_benchmark.py`](./scenario10_hidden_outcome_benchmark.py), [`scenario9_evidence_policy.py`](./scenario9_evidence_policy.py), and [`recovery_policy_benchmark.py`](./recovery_policy_benchmark.py) — deterministic policy simulations.
- [`tests/test_research.py`](./tests/test_research.py) — 19 isolated `unittest` regressions using Flask's test client, Werkzeug's local server helper, and thread events.

The app binds only to `127.0.0.1`. All network/browser experiments here targeted a local server. The test hook and `/test/inflight/<operation_id>` probe are not production coordination or security mechanisms.

## 5. Recovery decision logic

1. **Committed, matching, fresh simulated evidence:** confirm the mock record and do not retry.
2. **Absent, matching, fresh simulated evidence:** label it `OBSERVED_ABSENT`; the current policy retries with the same idempotency key. This is an observation-time decision, not proof of finality.
3. **Stale, mismatched, untrusted, conflicting, future-dated, unavailable, or missing evidence:** defer; do not infer success or failure.
4. **No idempotency key:** two submissions can create two mock records.
5. **Same idempotency key and same payload:** a committed replay reuses the prior operation; a replay while the original is in its pre-commit interval receives an in-progress response without creating another record.
6. **Same key and different payload:** return HTTP 409.

The freshness validator checks simulated metadata and a caller-supplied Boolean trust label. It does not independently authenticate sources, establish remote truth, or prove that a remote operation is final.

## 6. Experiment design and reproducibility

The regression suite resets application state before and after each test. Scenario 12 uses `threading.Event` synchronization rather than timing guesses: the original request signals from its pre-commit hook, the test checks both `in_flight=True` and `recorded=False`, sends the retry, then releases and joins the original before reading final records.

The HTTP experiments were run against the updated Flask app on `127.0.0.1:5057`. The experiment scripts accept `BROWSER_RECOVERY_BASE_URL`; the server accepts `BROWSER_RECOVERY_PORT`. The pre-existing port-5055 listener was not terminated or altered.

The virtual environment reported Python **3.14.2**, Flask **3.1.3**, Werkzeug **3.1.9**, and Playwright **1.64.0**. Pylance import analysis found the external project imports `flask`, `playwright`, and `werkzeug`; no unresolved modules were reported. The regression suite otherwise uses the Python standard library.

## 7. Results

| Experiment | Status | Actual output / interpretation |
|---|---|---|
| Source import and route registration | PASS | Current `app.py` imported from the expected workspace path; one `/submit` registration and `/test/inflight/<operation_id>` present in its route map. |
| Existing port 5055 route | FAIL (stale/mismatched listener) | PID 12484 returned 404 for `/test/inflight/race-test-001`; `/status` had an older response shape. The exact reason the process served a different app map could not be established; it was not stopped. |
| Updated server on port 5057 | PASS | Startup printed resolved source path and route map; `/test/inflight/probe` returned HTTP 200. |
| Regression suite | PASS | `19 tests`, `OK`; includes submission, blind duplicate, same-key replay, 409 conflict, timeout/later commit, status unavailable, invalid input, reset while in flight, unexpected error cleanup, evidence rules, Scenario 12, and local server lifecycle. |
| Baseline browser retry | PASS | Both browser confirmations timed out; final mock status contained 2 records for `demo-001`. |
| Ambiguous outcome | PASS | Both cases yielded the same client observation `TIMEOUT`; after completion, commit case was recorded and non-commit case was not. |
| Idempotency experiment | PASS | First request timed out; replay used a different payload under the same key and received HTTP 409; one record remained. The dedicated Scenario 6 and regression test covered same-payload retries. |
| Idempotency conflict experiment | PASS | Same key with payload A returned HTTP 200; payload B returned HTTP 409; one record remained. |
| Scenario 5 — unavailable status | PASS (unknown outcome correctly retained) | Submission timed out; status check to the separate local port 5056 was unavailable; agent-side output remained `UNKNOWN`; later mock inspection showed the original operation had recorded. |
| Scenario 6 — retry comparison | PASS | Blind retry: 2 records. Same-key retry: 1 record. |
| Scenario 7 — repeatability | PASS | Blind retry: duplicates in **20/20**, **40 total**. Same-key retry: duplicates in **0/20**, **20 total**. These are local mock runs only. |
| Scenario 8 — reconciliation | PASS | Commit-on case had a record at later mock observation. Commit-off case had no record at that observation and the same-key retry created one. This does not establish a general finality guarantee. |
| Recovery browser demo | PASS | Timed-out client found the mock record and skipped retry; final count was 1. |
| Scenario 9 — evidence policy | PASS | Fresh committed and observed-absent cases selected their configured actions; stale/unavailable/conflicting evidence deferred. |
| Recovery policy benchmark | PASS (synthetic) | 200 cases per policy: blind retry had 200 retry decisions (100 duplicate-risk, 100 incomplete-risk); never-retry had 200 stop decisions (100 incomplete-risk); defer/reconcile had 200 pending decisions. Pending is not completion. |
| Scenario 10 — hidden-outcome benchmark | PASS (synthetic) | **600 deterministic cases**; **200 correctly resolved**, **0 false-commit**, **0 unsafe-retry**, **400 deferred**. Not 600 independent real-world experiments. |
| Scenario 11 — evidence freshness | PASS (synthetic) | Fresh matching committed -> no retry; fresh matching absence -> observed-absent and same-key retry policy; stale, hash mismatch, untrusted, conflicting, future, and no evidence -> defer. |
| Scenario 12 — deterministic in-flight race | PASS | Both cases showed **0 records before retry** while original was in the pre-commit hook. Final: **2** without idempotency; **1** with same key and payload. Both request threads completed. |

All listed runnable scripts exited with code 0. Scenario 5's status endpoint was intentionally unavailable; that output is a scenario result, not a failed experiment.

## 8. Baselines and comparisons

- Blind retry has the simplest client behavior but duplicates an already-committed operation in the mock's tested timeout conditions.
- Never retry avoids duplicate requests but can leave an uncommitted intended action incomplete.
- Same-key retries suppress duplicates in this process-local mock, including while the initial call is pending.
- Defer/reconcile avoids unsupported decisions while evidence is unavailable or conflicting, but deferred work remains unresolved.

The mock demonstrates mechanics, not comparative real-world reliability. Its in-memory state, request timing, and deterministic synthetic labels are not representative evidence for deployed browser agents or remote systems.

## 9. Known limitations and failure modes

- State and idempotency records disappear at process restart; there is no persistent database or cross-worker coordination.
- The in-memory key reservation and record insertion are not a durable transaction and are unsuitable for production.
- No real browser/site integration was tested. The GUI/browser scripts exercise only the local page and mock API.
- A response lost after commit remains ambiguous from the client's perspective.
- A missing record in a status snapshot can become stale immediately and is not proof of non-commit.
- `source_trusted` is caller-provided metadata. Sequence numbers are not used as a freshness/finality proof.
- The mock does not model crashes at every storage boundary, network partitions, concurrent server processes, authentication, authorization, adversarial clients, or irreversible external side effects.
- Scenario 5 models an unavailable status service by using an unserved local port. Its exact connection failure mode can vary by host configuration.

## 10. Threats to validity

- Browser experiment trials are controlled runs against one in-memory local process, not independent production requests.
- The synthetic benchmarks repeat a small fixed set of scenarios. Counts are deterministic and do not establish statistical significance.
- Hidden outcomes are known to the benchmark evaluator by construction; real clients cannot see those labels.
- The chosen delays and local operating-system scheduling may not represent target websites, browsers, proxies, or distributed systems.
- The simulated evidence trust and timestamp values are assumptions supplied by the test generator.
- The initial 5055 incident demonstrated a process/source mismatch, but because the running process did not expose its loaded module path or working directory, its precise launch cause remains unresolved.

## 11. Security and reliability considerations

- Do not point this prototype at real sites or use it for bookings, payments, purchases, account changes, or other external operations.
- Keep the server bound to loopback. It has no authentication or production access controls.
- The test probe exposes mock operation state; it is only for local experiments.
- An idempotency key helps only when the actual target service contract enforces it consistently and atomically with its side effect.
- Use explicit unresolved/deferred outcomes when evidence is unavailable or cannot be trusted. Never translate a timeout into proof of failure.
- The test suite verifies a generic 500 response and cleanup after a deliberately injected server exception; production error disclosure, logging, and privacy behavior have not been assessed.

## 12. Patentability research gaps and scoped prior-art review

The title and concept remain hypotheses. Ordinary retries, idempotency keys, status checks, evidence age checks, provenance labels, and reconciliation are known design patterns and cannot be presented as novel based on this repository.

### Search performed on 2026-10-23

1. **Published patent application candidate supplied by the project:** US 2026/0252366 A1, described in the supplied reference as “Automating Web-Based Tasks.” The [USPTO Patent Public Search portal](https://ppubs.uspto.gov/pubwebapp/) and [USPTO publication PDF endpoint](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/20260252366) were reachable. The PDF endpoint yielded a scanned/image document rather than extractable claim text in this review; the Justia page returned 403 and the corresponding Google Patents page returned 404. Therefore the exact bibliographic details, publication date, jurisdiction-specific status, and independent claims were **not verified from readable primary-source text**. The title and broad characterization above are reported as supplied by the project, not as a claim construction or verified claim summary. A patent professional should retrieve the official file and review its claims and prosecution record.
2. **Granted patents:** no grant or grant number was verified in this scoped check. This is not evidence that relevant grants do not exist.
3. **Technical publication:** the arXiv search surfaced [“Step-Aligned Script Generation with Verification and Recovery for Web Automation Testing,” arXiv:2610.25601v1](https://arxiv.org/abs/2610.25601v1), posted 2026-10-19. Its abstract describes step-level provenance, verification, repair, and reversibility-aware backtracking for web automation tests. It is an adjacent technical publication worth comparing; its relation to any eventual filing depends on the actual claims and relevant priority dates.
4. **Technical engineering literature:** AWS Builders’ Library, [“Making retries safe with idempotent APIs”](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/), explains caller-provided request identifiers, repeat request handling, and the need for atomic handling of idempotency records and mutations. This is relevant background for the project's ordinary idempotency mechanism, not evidence of novelty for the current prototype.
5. Searches were focused, not exhaustive. The web checks did not establish worldwide patent family coverage, priority dates, legal status, prosecution history, or a complete non-patent literature landscape. The queried records must be checked against the proposed claims and the actual invention/priority date before drawing conclusions.

### Legal/filing cautions

- For an Indian filing, consult a qualified Indian patent agent on Section 3(k), current Computer Related Inventions guidance, inventorship, ownership, enablement, and claim scope. No legal opinion is provided here.
- A PCT application is an international filing route, not a worldwide patent. For an Indian resident considering foreign filing, check the current Patents Act Section 39 requirements and any applicable permission/first-filing obligations with a patent professional before filing abroad.
- Preserve confidentiality and document the actual technical contribution, inventorship, ownership, and dates. Do not draft broad claims from these demonstration scripts alone.

## 13. Recommended next steps

1. Define a narrower technical contribution beyond conventional idempotency, retry, and status reconciliation.
2. Specify the operation lifecycle and evidence trust model, including crash points and what constitutes final evidence.
3. Prototype durable atomic idempotency state and recovery against a fault-injection test harness; do not claim those semantics until implemented and tested.
4. Add multi-process/concurrent-client trials and measurable baselines before making reliability claims.
5. Ask a patent agent to review the original publication's official claims and search neighboring patent families and literature after the technical differentiation is clearer.
6. If filing deadlines, public disclosure, or foreign filing are time-sensitive, obtain an initial confidential patent-agent consultation now. The current results do not justify a patentability claim or a filing recommendation.

## 14. Exact reproduction commands

From the project directory in PowerShell, run the tests and synthetic checks:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe .\scenario9_evidence_policy.py
.\.venv\Scripts\python.exe .\scenario10_hidden_outcome_benchmark.py
.\.venv\Scripts\python.exe .\scenario11_evidence_freshness.py
.\.venv\Scripts\python.exe .\recovery_policy_benchmark.py
.\.venv\Scripts\python.exe .\scenario12_inflight_race.py
```

Run the HTTP experiments on an isolated port so an existing 5055 listener is not disturbed:

```powershell
$env:BROWSER_RECOVERY_PORT = "5057"
.\.venv\Scripts\python.exe .\app.py
```

In a second PowerShell window, from the same project directory:

```powershell
$env:BROWSER_RECOVERY_BASE_URL = "http://127.0.0.1:5057"
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

The tested environment was the existing `.venv` Python 3.14.2. Browser experiments additionally require Chromium installed through Playwright. No command above targets an external service.
