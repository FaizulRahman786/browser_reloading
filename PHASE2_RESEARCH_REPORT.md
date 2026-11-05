# Phase 2 Research Report: Candidate Recovery Mechanisms

**Date:** 2026-10-23  
**Project:** Local-only browser-recovery prototype  
**Disposition:** One candidate implemented and tested in an isolated simulator, but **not selected for advancement**. It improves some aggregate mock metrics while producing false commit confirmations and unsafe retries in explicit counterexamples. Novelty, inventive step, patentability, and production readiness are **NOT ESTABLISHED**.

## 1. Executive summary

Phase 2 reviewed the existing baseline, identified the gap between a time-of-observation status snapshot and a final outcome, conducted a scoped prior-art review, and compared four policies over the same 10 deterministic synthetic scenarios (20 repetitions each).

The experimental candidate, a **distinct-source quorum plus bounded settlement gate**, requires two fresh source labels to agree and waits for a configured completion horizon before acting on `ABSENT`. In the simulator it resolved 80/200 cases versus 60/200 for evidence-based deferral and reduced duplicate side effects from 40 to 20 and unsafe retries from 40 to 20. However, it generated **20 incorrect commit confirmations**, caused by the deliberately included two-source false quorum. It also caused 20 duplicates and unsafe retries when a delayed commit arrived after the configured duration bound. Its mean modeled latency was 175 ms, versus 80 ms for evidence deferral and 100 ms for blind/idempotency retry.

These results do not support accepting the candidate as a safe recovery mechanism. They show a measurable tradeoff and the need to make source independence, status consistency, and operation-finality assumptions explicit. The existing Flask baseline and prior experiment files were not modified for Phase 2. The new simulator and tests are separate.

## 2. Existing baseline and failure cases

| Existing approach | What it does | Unresolved failure cases |
|---|---|---|
| Blind retry | Reissues the action after uncertainty without reconciling. | If the first request commits, the retry can create a duplicate. A changed payload may create a different action. |
| Idempotency-key protection | Reuses the same key and payload so a capable server can deduplicate. | Does not help when the remote system lacks this contract, loses its key state, applies the side effect outside the key's transaction, or receives a changed payload. |
| Status polling | Checks the mock `/status` record list after timeout. | A request can commit after an `ABSENT` snapshot; a response may be stale, cached, or from an eventually consistent replica. A status endpoint may be unavailable or report inconsistent views. |
| Evidence freshness | Rejects evidence older than the configured threshold, future-dated, mismatched, or labeled untrusted. | Timestamps and Boolean trust labels are supplied metadata. Freshness does not imply authenticity, consistency, or finality. |
| Deferral on missing/conflicting evidence | Leaves the result unresolved rather than guessing. | Avoids unsupported claims but can leave recoverable actions unresolved and increases latency. It cannot distinguish temporary disagreement from permanently unavailable evidence. |

Required failure cases are represented in the simulator:

1. **Commit after absence:** a scenario returns two fresh `ABSENT` values, but the original operation eventually commits after the supposed maximum duration.
2. **Stale response:** a 30-second-old `ABSENT` observation is ignored by the freshness validator while fresh committed observations remain usable.
3. **Conflicting independent sources:** two fresh `COMMITTED` observations and one fresh `ABSENT` observation.
4. **Changed retry payload:** the proposed retry differs from the initiating payload; blind retry proceeds, same-key protection conflicts, and evidence/candidate policies defer.
5. **No idempotency support:** repeated side effects are possible under retry.
6. **No consistency guarantee:** a single replica reports `ABSENT` while the original eventually commits; a two-source method lacks quorum and defers.
7. **False quorum:** two fresh, separately named sources say `COMMITTED` even though the true outcome is not committed.

## 3. Prior-art review (focused, not exhaustive)

Sources were checked on **2026-10-23**. The documents below are relevant background, not a novelty search or legal opinion. Claim-level statements are made only where claim text was available and verified; none of the following is asserted as a claim chart.

### Published patent applications

- **US 2026/0051378 A1, “Hybrid data synchronizer.”** Google Patents search metadata reports priority **2024-08-19** and publication **2026-02-19**. [Google Patents publication page](https://patents.google.com/patent/US20260051378A1/en). The related EP publication [EP 4 721 105 A1](https://patents.google.com/patent/EP4721105A1/en), description paragraphs **[0005]–[0006]**, discuss acquisition through agentic/UI-driven interfaces and writeback mechanisms that may be idempotent and reversible. The US page description also discusses writeback safety concepts including idempotency keys, precondition checks, rollback, and audit logging. This is adjacent disclosure, not a verified claim on the candidate mechanism. **The independent claims, prosecution history, current legal status, and complete family record were not verified in this review.**
- **US 2026/0252366 A1, “Automating Web-Based Tasks,”** was supplied as a prior-art lead in Phase 1. Its Google Patents page was not found at the queried identifier; the USPTO publication PDF endpoint was image/scanned content, and the Justia source was unavailable. Bibliographic details and claim text were **not verified**. No argument in this report depends on its claim scope.
- No granted patent is relied upon in the comparison. This is not a finding that relevant grants do not exist.

### Technical publications

- **Dhulipala et al., “Step-Aligned Script Generation with Verification and Recovery for Web Automation Testing,” arXiv:2610.25601v1, posted 2026-10-19.** [arXiv record](https://arxiv.org/abs/2610.25601v1) and [HTML text](https://arxiv.org/html/2610.25601). The abstract describes step-level provenance, goal-state assertions, repair history, a syntactic/execution/semantic-oracle verification pipeline, and reversibility-aware backtracking around likely commit points. Its Section V reports script-generation/recovery evaluation. It addresses web-test script generation and repair, not proof that an ambiguous remote side effect did or did not commit; it is nevertheless close prior technical work on browser recovery and verification.
- **Zhou et al., “WebArena: A Realistic Web Environment for Building Autonomous Agents,” arXiv:2307.13854 (2023).** [arXiv record](https://arxiv.org/abs/2307.13854). It provides a realistic web environment and agent interaction benchmark. It is relevant to evaluation methodology, not a claim that it solves ambiguous commits.

### Ordinary engineering techniques and standards

- **HTTP Semantics, RFC 9110, Section 9.2.2 (“Idempotent Methods”).** [RFC text](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2). The section says a client SHOULD NOT automatically retry a non-idempotent method without knowing its semantics are idempotent or having a means to detect that the original request was never applied. This directly covers the generic retry risk; it is a protocol standard, not a patent.
- **AWS Builders’ Library, “Making retries safe with idempotent APIs.”** [Article](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/). The passages on caller-provided request identifiers describe deduplicating retries while preserving caller intent. The article also states that combining idempotency-token recording and mutations should be an atomic, all-or-nothing server operation. This is an established engineering technique and closely matches Phase 1's idempotency baseline.
- **Quorum reads, freshness bounds, conditional writes, retry budgets, and local operation journals** are established distributed-systems patterns. Their mere combination with browser automation is not evidence of novelty.

### Limits of this prior-art work

Searches used patent publication pages/search snippets and accessible technical publications. They did not establish a complete patent family, legal status, priority-date analysis, independent-claim comparison, prosecution history, worldwide coverage, or exhaustive non-patent literature. The scanned US source from Phase 1 remains unverified. A qualified patent professional would need to run a claim-focused search against a defined technical contribution and filing date.

## 4. Three candidate mechanisms considered

### Candidate A — Distinct-source quorum with bounded settlement gate

- **Problem:** One current or stale status response can mislead an agent, while evidence deferral can leave even consistent multi-source observations unresolved.
- **Mechanism:** Bind each observation to operation ID and original payload hash; reject stale/future/untrusted/mismatched observations; count one vote per source label; require at least two distinct sources to agree. For `ABSENT`, wait until a configured maximum operation duration has elapsed, read the sources again, and retry only if a fresh post-window quorum still agrees and the payload matches.
- **Difference from Phase 1:** Phase 1 accepted consistent usable evidence or deferred on conflicting usable evidence; it did not have a multi-source vote threshold or an operation-age gate.
- **Closest approaches:** Quorum reads and consistency protocols; HTTP conditional requests; idempotency APIs; the status/evidence patterns above.
- **Weaknesses/prior art risks:** Source labels do not prove source independence; replicas can share a faulty cache or upstream. Two sources can both be wrong. A maximum duration is only safe if contractually guaranteed and correctly measured. An `ABSENT` quorum still is not finality absent such guarantees. The principal elements are conventional engineering techniques.
- **Test:** Compare against all three baselines on the same fixed cases, including false majority, a late commit beyond the declared bound, stale and conflicting observations, changed payload, and no idempotency support. Measure duplicates, false confirmations, unsafe retries, resolved/deferred cases, and modeled latency.

### Candidate B — Payload-frozen local operation journal

- **Problem:** An automation agent may regenerate or alter form fields during retry, making a retry a different action even when the human intent was unchanged.
- **Mechanism:** Before the first submit, create a local immutable intent record with operation ID, canonical payload hash, key (if supported), target/action fingerprint, and initial observation. Any retry is constructed from that saved payload; an attempted change creates a new operation identity or requires explicit review. Store evidence and recovery decisions as journal events.
- **Difference from Phase 1:** Phase 1 hashes payloads server-side and rejects same-key/different-payload reuse. It has no client-side durable intent journal or retry-payload freeze.
- **Closest approaches:** Idempotency keys, transactional outbox/inbox, write-ahead logs, request signing, and audit/event logs. AWS's idempotency guidance is directly relevant; the hybrid synchronizer application also describes idempotent/reversible writeback concepts.
- **Weaknesses/prior art risks:** A client journal cannot reveal whether a non-idempotent remote side effect already committed; local storage can be lost or roll back. The idea is likely close to commonplace durable-workflow and idempotency practice.
- **Test:** Inject a client crash after submit and before response; restart from the journal; mutate the visible form; verify frozen payload, conflict detection, and no accidental changed-payload resend. Compare duplicate rate and recovery success with and without the journal.

### Candidate C — UI semantic state-delta and commit-point guard

- **Problem:** Browser automation may infer success from a click or a generic confirmation message even though the page did not reach the intended postcondition, or may blindly replay an irreversible step while repairing a workflow.
- **Mechanism:** Capture a minimal semantic pre-action snapshot and expected postcondition; after ambiguity, inspect a bounded set of DOM/accessibility signals, compare state deltas, classify the action as reversible/irreversible, and prohibit replay of an irreversible step until evidence or operator review resolves the state.
- **Difference from Phase 1:** Phase 1 evaluates mock server status/evidence; it does not inspect pre/post DOM semantics or action reversibility.
- **Closest approaches:** Browser test oracles, state-based verification, UI assertions, TESSARA's step-aligned provenance/verification and reversibility-aware backtracking, and WebArena-style evaluation.
- **Weaknesses/prior art risks:** UI state can be stale, misleading, localized, or generated optimistically; DOM deltas can miss hidden server-side effects. TESSARA is particularly relevant prior work in verification and backtracking. This candidate is broader and less sharply measurable than A without a robust benchmark.
- **Test:** In a local site simulator, vary confirmation banners, delayed DOM updates, optimistic UI, hidden commit, and irreversible actions. Measure false-confirmation and unsafe-replay rate, task completion, latency, and abstention.

## 5. Selection and implementation disposition

Candidate A was selected **for a bounded experiment only** because its inputs and proposed effects were testable in the existing synthetic simulator, and it makes the distinction between observation and a declared settlement horizon explicit. It is **not selected for advancement**: the controlled counterexamples show it is unsafe when its assumptions fail.

Added [`phase2_recovery.py`](./phase2_recovery.py) with policy functions:

- `blind_retry`
- `idempotency_only`
- `evidence_deferral` (the Phase 1 evidence policy)
- `quorum_settlement_gate` (Candidate A)

This is a local deterministic policy simulator. It does not alter [`app.py`](./app.py), the existing experiment files, or the Phase 1 test suite. It models a remote capability through scenario parameters; it does not add a remote idempotency feature.

The candidate requires:

1. At least two usable votes from distinct source labels.
2. Matching operation ID and original payload hash, fresh timestamps, and `source_trusted=True`.
3. A unique status with at least two votes.
4. For absence, expiry of the configured duration bound and a fresh post-window absence quorum before retry.
5. A retry payload matching the original operation.

The model treats source labels/trust flags and operation duration bounds as assumptions, not independently authenticated facts.

## 6. Methodology and metric definitions

- **Scenario set:** 10 named, deterministic cases; repeated 20 times per policy (200 policy-cases). Repetition is for stable aggregation only, not independent randomized trials.
- **Identical inputs:** Each policy sees the same case definitions and hidden eventual outcome. Policies differ only in their action rules.
- **Duplicate operations:** Count of extra side effects beyond one per logical operation, aggregated across 200 cases.
- **Incorrectly confirmed commits:** A policy chooses `CONFIRM_COMMITTED` when the modeled original does not eventually commit.
- **Unsafe retries:** A retry is counted if the original eventually commits and the retry is not deduplicated, yielding multiple side effects.
- **Successfully resolved:** A correct committed confirmation or a matching retry that produces exactly one side effect.
- **Deferred:** The policy returns a defer action.
- **Unresolved:** Any case not successfully resolved; includes deferrals, false confirmations, and rejected payload conflicts.
- **Payload conflicts:** The modeled idempotency endpoint rejects a mismatched payload under the same key.
- **Recovery latency:** **Modeled cost**, not wall-clock timing. Retry round trip = 100 ms, a parallel status-read batch = 50 ms, and the candidate adds any remaining wait to the configured duration bound plus a post-window status-read batch when needed. These fixed costs are explicit assumptions and not measured network latency.

The simulator's `original_eventually_commits` value is ground truth available only to the evaluator. The policy functions do not receive that field when choosing the action.

## 7. Actual results

Command:

```powershell
.\.venv\Scripts\python.exe .\phase2_recovery.py
```

Actual aggregate output:

| Policy | Duplicate operations (extra effects) | Incorrect confirmations | Unsafe retries | Successfully resolved / 200 | Deferred / 200 | Unresolved / 200 | Payload conflicts | Modeled latency total | Mean modeled latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Blind retry | 140 | 0 | 140 | 60 | 0 | 140 | 0 | 20,000 ms | 100 ms |
| Idempotency-only | 80 | 0 | 80 | 100 | 0 | 100 | 20 | 20,000 ms | 100 ms |
| Evidence deferral | 40 | 0 | 40 | 60 | 100 | 140 | 0 | 16,000 ms | 80 ms |
| Quorum + settlement gate | 20 | 20 | 20 | 80 | 80 | 120 | 0 | 35,000 ms | 175 ms |

Selected per-case outputs for Candidate A (20 repeats each):

| Case | Candidate action | Result |
|---|---|---|
| Fresh commit consensus | `CONFIRM_COMMITTED` | Correctly resolved. |
| Settled absence consensus, no idempotency | `RETRY` | One side effect; resolved. |
| Commit after declared absence bound | `RETRY` | **20 duplicate side effects and 20 unsafe retries** across the repeated case. |
| Stale absence plus fresh commit quorum | `CONFIRM_COMMITTED` | Stale observation rejected; correct in this simulation. |
| Fresh 2-to-1 conflict (true commit) | `CONFIRM_COMMITTED` | Resolves a case the evidence-deferral policy defers. |
| False 2-to-1 commit quorum | `CONFIRM_COMMITTED` | **20 false commit confirmations** across the repeated case. |
| Absence before the duration bound | Wait, then re-read | Requires a new post-window absence quorum; in the settled-absence case it takes 1,200 modeled ms before retry. |
| Changed retry payload | `DEFER_PAYLOAD_MISMATCH` | Candidate deferred; idempotency-only returned 20 conflicts; blind retry generated 20 extra effects. |
| No status and no remote idempotency | `DEFER` | Unresolved, no candidate retry. |
| Single inconsistent absence source | `DEFER` | Quorum unavailable, no candidate retry. |
| Untrusted agreeing sources | `DEFER` | Evidence rejected, no candidate retry. |

Interpretation: Candidate A lowered the measured duplicate and unsafe-retry totals versus evidence deferral in this scenario set and resolved more cases, but did so at the unacceptable cost of false confirmations. Its late-commit counterexample also proves that a duration estimate is not a finality guarantee. The score is scenario-dependent; it is not a production reliability estimate.

## 8. Tests and outcomes

New separate tests: [`tests/test_phase2.py`](./tests/test_phase2.py).

Command:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_phase2.py" -v
```

**PASS:** 10 tests. Assertions cover identical inputs/counts, a resolved conflict case, fresh post-settlement reread, the late-commit failure, false quorum, evidence deferral on insufficient/untrusted inputs, changed-payload handling, aggregate tradeoffs, modeled latency, and policy registration.

The existing Phase 1 suite was not changed. It was run together with the new suite: **29 tests passed, 0 failed**. Run the Phase 1 tests alone with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_research.py" -v
```

No test was designed to make the candidate always succeed; the late-commit and false-quorum tests explicitly assert failure modes.

## 9. Limitations and threats to validity

- All cases are synthetic and fixed; a repeat count does not create independent evidence.
- Source independence is represented by distinct strings. The model cannot establish organizational, software, or data-path independence.
- `source_trusted=True` is an input label; no identity, signature, transport, or provenance verification is performed.
- A majority can be correlated or uniformly wrong, as the false-quorum case demonstrates.
- A declared maximum operation duration can be wrong; late commit after that point recreates duplicate risk.
- Status age is measured relative to the simulator's clock. Clock skew and replica lag are not modeled.
- A stable `ABSENT` value across repeated reads still does not prove no future commit unless the remote service provides finality semantics.
- The idempotency-only policy is modeled to deduplicate only when the scenario says the target supports it and only when the retry payload matches.
- Recovery latency is a model with fixed costs, not a timed benchmark.
- The simulator does not model real websites, browser rendering races, service crashes, persistence, authentication, or external side effects.

## 10. Next experiment

Do not advance Candidate A as a product or patent concept on these results. A useful next experiment would need a local fault-injection service with explicit guarantees and randomized fault schedules:

1. Simulate replicas with separately controllable staleness, correlated failures, clock skew, and delayed commits.
2. Define a service-enforced terminal watermark or explicit operation-completion contract; do not infer finality from repeated absence reads.
3. Separate operation identity from payload version and verify that changed intent cannot silently reuse a key.
4. Compare false-confirmation, duplicate, unsafe-retry, completion, abstention, and P50/P95 recovery latency across randomized seeded trials.
5. Include ablations for one source vs quorum, no horizon vs declared horizon, and trusted vs untrusted evidence; publish seeds and all raw cases.
6. Revisit Candidate B only if client-side durable journaling can be tested across real crash/restart boundaries and demonstrates value beyond ordinary idempotency/outbox patterns.
7. Conduct a claim-specific patent search only after the technical mechanism is narrowed. Current work does not justify novelty, inventive-step, patentability, or production-readiness claims.

## 11. Reproduction

From the project directory in PowerShell:

```powershell
.\.venv\Scripts\python.exe .\phase2_recovery.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_phase2.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_research.py" -v
```

These commands need no Flask server and make no external requests. The prior-art web research was separate from the local experiment runs.
