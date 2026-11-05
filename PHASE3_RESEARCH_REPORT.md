# Phase 3 — Verifiable Finality and Evidence Independence

## Executive summary

Phase 3 replaces source-counting as a safety argument with a narrow controller contract: confirm only from an operation-bound, authenticated, integrity-validated receipt whose service semantics are documented, or from an authoritative terminal status governed by an explicit finality guarantee. A same-payload retry is side-effect-safe only when the service contract makes idempotency-key handling atomic with the effect. It still does not establish completion unless a validated terminal response is returned.

The implementation is a local deterministic model, not a service integration. Across 15 scenarios repeated 20 times per policy (300 cases per policy), the guarantee-aware controller produced no duplicate side effects, false commit confirmations, or unsafe retries; it resolved 80 cases and left 220 unresolved. The conservative policy also avoided those three hazards but resolved only 60. Neither result demonstrates real-world reliability or a distinct invention. The Phase 2 quorum-and-wait candidate remains unchanged as a rejected baseline: it generated 40 duplicate side effects, 20 false commit confirmations, and 40 unsafe retries in this expanded fixture set.

**Recommendation:** Do not advance the Phase 2 quorum or describe the Phase 3 contract as novel or patentable. The Phase 3 result restates service guarantees and well-established idempotency, transaction, workflow, and reconciliation practices. Stop the patent-directed path unless a later implementation establishes a concrete service-verifiable capability that is not supplied by ordinary service APIs and can be compared against specific verified patent claims.

## 1. Research question

Can service-verifiable operation finality and evidence provenance permit safe recovery after an ambiguous browser action, without treating a missing status record, a timestamp, multiple source names, or a bounded wait as proof that an operation cannot commit later?

The simulation compares:

1. Blind retry.
2. Idempotency-only retry.
3. Conservative evidence deferral.
4. The unchanged Phase 2 quorum-and-settlement implementation.
5. A Phase 3 guarantee-aware controller.

No browser form, payment, booking, account action, or external transaction was submitted. All fixtures and side effects are local synthetic data.

## 2. Baseline and assumptions

The existing prototype's relevant baseline is:

| Existing approach | Current behavior | Unresolved risk |
|---|---|---|
| Blind retry | Replays after an ambiguous result. | The original request may commit as well, producing a duplicate; the replay may differ from the initiating payload. |
| Idempotency-key protection | The Phase 1 mock deduplicates same-key/same-payload requests and rejects key reuse with a different payload. | This is an in-memory mock behavior, not proof that a remote service atomically records the key with its side effect. Many targets do not support keys. |
| Status polling | Reads a status snapshot after a timeout. | A request may commit after an absence snapshot; a response can be stale, cached, inconsistent, or unavailable. |
| Evidence freshness checks | Rejects stale, future-dated, mismatched, or untrusted-labelled evidence according to metadata. | Fresh timestamps and Boolean trust labels do not prove authenticity, source independence, consistency, or finality. |
| Deferral | Missing or conflicting evidence remains unresolved rather than being guessed. | Safe but may remain unresolved indefinitely and does not itself reconcile or complete work. |
| Phase 2 quorum and wait | Counts fresh evidence under different source names, waits to a declared horizon for absence, reads again, and may retry. | Names do not establish lineage independence; a cache can return stale content with a fresh observation time; a declared duration does not prove that a commit cannot arrive later. Phase 2 recorded 20 false confirmations and late-commit duplicates in its earlier benchmark. |

The following are **model assumptions**, not properties implemented by this repository or proven about a real remote service:

- The controller has a stable operation ID and immutable expected payload hash.
- Fixture fields `authenticated`, `authority`, and `receipt_valid` stand in for successful verification. No cryptographic signature, certificate chain, service identity, or trusted clock is implemented.
- `provenance_root` represents declared common lineage/cache ownership. It is fixture metadata, not discovered from live infrastructure.
- A service guarantee is configured explicitly and truthfully. A Boolean in the simulator is not proof that a real service honors that contract.
- When an idempotent retry has documented receipt semantics, the simulated retry response is received and validated. A retry whose response is lost remains `UNKNOWN`, even though its side effect is protected from duplication.
- Modeled operation truth is set by each scenario. No random fault schedule, wall-clock latency measurement, or real service was used.

## 3. State-machine specification

`phase3_finality.py` defines `REQUESTED`, `IN_FLIGHT`, `COMMITTED`, `PROVEN_NOT_COMMITTED`, `UNKNOWN`, and `CONFLICTING_EVIDENCE`.

| State | Evidence required in this model | Permitted conclusion/action |
|---|---|---|
| `REQUESTED` | A local intent/operation record exists. A request being sent does not prove receipt by the service. | No remote outcome claim. |
| `IN_FLIGHT` | A fresh, authenticated observation bound to the expected operation ID and payload hash; the service is configured as authoritative for status; and the observation explicitly says in-flight. | Do not retry merely because it remains in flight. Poll/reconcile or defer. |
| `COMMITTED` | Either (a) a matching authenticated receipt marked integrity-valid and covered by documented receipt semantics, or (b) a matching authoritative terminal status under a service contract that guarantees terminal finality. | Confirmation is allowed. A UI banner or ordinary non-authoritative status is insufficient. |
| `PROVEN_NOT_COMMITTED` | A matching, fresh, authenticated authoritative terminal non-commit response, plus a service guarantee that this terminal result cannot later become a commit. | A new attempt can be considered; use the exact frozen intent. |
| `UNKNOWN` | No adequate evidence, including a missing record, stale or mismatched evidence, a non-authoritative absence, an unauthenticated source, or an unresolved status. | Do not report completion. Defer for reconciliation or human intervention unless the exact-payload idempotency contract independently makes retry side-effect-safe. |
| `CONFLICTING_EVIDENCE` | Fresh authenticated operation-bound observations disagree and no applicable authoritative terminal result resolves the disagreement. | Neither confirm nor retry automatically. Reconcile. |

An `ABSENT` snapshot is not `PROVEN_NOT_COMMITTED`; it records only that no matching item appeared in that source's view at that observation time. It cannot rule out a delayed commit. Different names or URLs do not establish independence. In the simulator, the declared `provenance_root` exposes two replica labels that share one cache. The Phase 2 policy intentionally continues to count source labels, so the fixture can show its failure.

An explicit authoritative terminal result may take precedence over a nonterminal lower-authority observation in this model. Contradictory authoritative terminal evidence remains conflicting. A stale status is discarded before classification. Exact binding and freshness are necessary, but not sufficient, for finality.

## 4. Evidence provenance model

Each `Observation` contains:

- `source_id`: display/source label (not an independence proof).
- `provenance_root`: declared common lineage/cache origin.
- `operation_id` and `payload_hash`: binding to the initiating action.
- `state` and `age_seconds`: reported value and freshness fixture.
- `authenticated`, `authority`, `terminal`, and `receipt_valid`: explicit modeled verification/semantic inputs.

`ServiceGuarantees` separately records idempotency support, whether idempotency is atomic with the side effect, authoritative status, terminal finality, and documented receipt semantics. This separation avoids inferring a service guarantee from a status value or source label.

The Phase 3 implementation has no quorum rule. Agreement by non-authoritative sources, even independent ones, does not become finality. Independent observations that disagree become `CONFLICTING_EVIDENCE`; matching observations with no terminal guarantee remain `UNKNOWN`. Provenance roots are retained so tests can distinguish same-cache labels from distinct fixture roots, but the controller does not claim to discover or cryptographically prove those roots.

## 5. Deterministic test scenarios

The same 15 fixtures are provided to every policy, with 20 identical repetitions per fixture:

| Scenario | Fixture and intended conclusion |
|---|---|
| `verified_commit_receipt` | Matching authenticated, integrity-valid receipt with documented semantics permits confirmation. |
| `authoritative_terminal_no_commit` | Authoritative terminal proof permits a safe new attempt because the initial operation cannot commit later. |
| `shared_stale_cache_two_names` | Two fresh-looking source labels share one cache lineage. Their agreement does not prove finality; the Phase 2 source-name quorum retries. |
| `independent_observations_disagree` | Distinct provenance roots report conflicting outcomes; remain unresolved. |
| `primary_consistent_commit` | Explicit authoritative primary terminal commit can confirm despite a contradictory non-authoritative replica view. |
| `cannot_establish_if_in_flight` | A source that cannot establish in-flight state yields `UNKNOWN`. |
| `stale_status_response` | A 30-second-old terminal-looking status is rejected under the 10-second modeled freshness limit. |
| `commit_after_absence_snapshot` | Two labels backed by one cache report absence after the candidate's declared duration; the original operation commits later. The Phase 2 candidate retries and duplicates. |
| `mismatched_operation_or_payload` | Wrong operation ID and wrong payload hash prevent evidence from being applied to the requested operation. |
| `idempotency_without_status` | Atomic same-key/same-payload idempotency with documented receipt semantics allows a retry without a status endpoint. |
| `idempotency_without_verifiable_retry_receipt` | Retry is side-effect-safe, but absent documented/validated terminal receipt the result remains unknown. |
| `idempotency_not_atomic_with_effect` | A key feature without atomic key/effect semantics does not authorize an automatic retry. |
| `neither_idempotency_nor_authoritative_status` | No safe automatic retry is available; defer for reconciliation/human intervention. |
| `changed_payload_same_key` | A changed payload is rejected/deferred rather than reusing the same operation key. |
| `false_independent_commit_agreement` | Two independently labelled but non-authoritative commit observations are false; neither quorum nor agreement should establish a commit. |

The first, second, third, fourth, fifth, sixth, eighth, ninth, tenth, twelfth, and thirteenth scenarios directly exercise the requested evidence/guarantee fixtures. Additional scenarios cover stale responses, retry-response ambiguity, non-atomic key semantics, changed payloads, and false consensus.

## 6. Comparative results

Run with:

```powershell
.\.venv\Scripts\python.exe .\phase3_finality.py
```

Actual output from 15 × 20 = **300 cases per policy**:

| Policy | Duplicate side effects | False commit confirmations | Unsafe retries | Correctly confirmed outcomes | Resolved | Deferred/unresolved | Deferred actions | Modeled latency total | Mean modeled latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Blind retry | 220 | 0 | 300 | 0 | 0 | 300 | 0 | 30,000 ms | 100.0 ms |
| Idempotency-only | 180 | 0 | 240 | 20 | 20 | 280 | 20 | 30,000 ms | 100.0 ms |
| Conservative evidence deferral | 0 | 0 | 0 | 60 | 60 | 240 | 240 | 17,000 ms | 56.7 ms |
| Phase 2 quorum-and-wait (rejected) | 40 | 20 | 40 | 0 | 0 | 300 | 240 | 19,000 ms | 63.3 ms |
| Phase 3 guarantee-aware controller | 0 | 0 | 0 | 80 | 80 | 220 | 200 | 18,000 ms | 60.0 ms |

Metric definitions:

- **Duplicate side effects:** extra side effects for the same frozen payload. A changed-payload retry is not called a duplicate of the original payload, but remains unsafe.
- **False commit confirmation:** the policy reports `COMMITTED` without a real initial commit or a valid commit receipt produced by its retry.
- **Unsafe retry:** a retry request is issued without an exact-payload atomic idempotency guarantee or authoritative proof that the initial operation is terminally not committed. This counts attempted unsafe retries even when a duplicate does not result.
- **Correctly confirmed outcome:** an accurate terminal commit or terminal non-commit conclusion.
- **Resolved:** the controller reaches an accurate terminal outcome. A side-effect-safe retry with an ambiguous/missing response is not resolved.
- **Deferred/unresolved:** no accurate terminal conclusion is established.
- **Modeled latency:** fixed policy costs (status read 50 ms, retry 100 ms, plus the Phase 2 candidate's modeled wait when applicable). It is not a wall-clock measure.

The Phase 2 candidate failures are visible in the per-case fixtures:

| Phase 2 case | Observed result (20 repetitions) |
|---|---|
| Two source labels sharing one stale cache | 20 duplicate side effects and 20 unsafe retries. |
| Commit after the absence observation and assumed duration | 20 duplicate side effects and 20 unsafe retries. |
| False independent commit agreement | 20 false commit confirmations. |

The Phase 3 guarantee-aware controller's actual actions were:

| Fixture group | Result |
|---|---|
| Verified receipt; authoritative primary commit | `CONFIRM_VERIFIED_COMMIT` |
| Authoritative terminal non-commit | Safe retry, then `COMMITTED` using the modeled validated retry response. |
| Atomic idempotency without status and with receipt semantics | `RETRY_SAME_KEY_CONFIRMED` |
| Atomic idempotency without a verifiable retry receipt | `RETRY_SAME_KEY_OUTCOME_UNKNOWN` (safe retry, unresolved result). |
| Shared cache, disagreement, unknown in-flight, stale/mismatched evidence, delayed commit after absence, non-atomic idempotency, no guarantees, false consensus | Defer/unknown; do not confirm or retry. |
| Changed payload under the same key | `DEFER_PAYLOAD_MISMATCH`. |

The guarantee-aware policy resolves 20 more cases than conservative deferral solely because the fixture grants atomic same-payload idempotency and, in one case, a verifiable retry receipt. This is a contract difference, not an inferred benefit from provenance scoring. It intentionally leaves 220 of 300 cases unresolved; that abstention is safer in the model, but it is not a complete recovery solution.

## 7. Failure cases and limits of the controller

- If a service never exposes authoritative status, atomic idempotency, or a verifiable receipt, the controller cannot safely automate a retry or report completion after an ambiguous result. Manual reconciliation is required.
- If a service claims but does not actually enforce atomic idempotency, the model's safe-retry conclusion is invalid. The non-atomic fixture demonstrates that the Boolean claim alone must not be treated as proof.
- A valid receipt still depends on the service's receipt semantics and actual verifier. The simulator's `receipt_valid=True` is an input, not a cryptographic implementation.
- Independently named status services may share a database, cache, replica, credential, or failure domain. Real lineage must be established outside this prototype.
- An authoritative status API that lacks terminal-finality semantics cannot turn absence into `PROVEN_NOT_COMMITTED`.
- Retry responses can be lost after a side effect. Idempotency can protect side-effect count while leaving the client outcome `UNKNOWN`.
- No independent execution of fault schedules, crashes, concurrent clients, clock skew, transport failures, service bugs, or long-duration delayed commits is performed.
- Fixed repeated fixtures are deterministic replications for output stability, not independent statistical trials. There are no confidence intervals or statistical significance claims.
- All latency figures are synthetic assigned costs.

## 8. Limitations and threats to validity

This work modifies only `phase3_finality.py`, `tests/test_phase3.py`, this report, and the Phase 3 reproduction section of `README.md`. Phase 1 and Phase 2 implementations and their reports remain intact. In particular, the Phase 2 quorum implementation remains runnable and is still measured as a rejected baseline.

The model is purpose-built to express the stated service-contract differences. It does not show that a browser automation system can obtain or verify these guarantees from arbitrary websites. The test oracle knows each scenario's hidden truth; a real controller generally does not. No real forms or transactions were used.

The comparator models a service's idempotency response as a validated commit receipt only when `receipt_semantics_documented` is true. This simplifying response model does not cover key expiry, key scoping errors, concurrent first submissions, payload canonicalization disagreements, downstream side effects outside the service transaction, or a broken implementation. Those require a separately instrumented service test.

## 9. Prior-art review

The following sources were consulted as technical background. This is a focused preliminary review, not a freedom-to-operate search or legal opinion.

### Patents and published applications

- **US 2026/0051378 A1, “Hybrid data synchronizer.”** Google Patents identifies the publication as a 2026 application and reports a 2024-08-19 provisional priority date. The corresponding EP 4 721 105 A1 description was inspected at paragraphs **[0018]–[0019]**: it describes acquisition through on-premises CDC, cloud/API integrations, and agentic UI automation, and discusses safe, reversible, idempotent writeback. This is adjacent disclosure on browser/UI integration and safe writes, not a verified claim chart against this prototype. **Independent claim text, prosecution history, current legal status, and complete family scope were not verified.** [US publication](https://patents.google.com/patent/US20260051378A1/en) · [EP publication](https://patents.google.com/patent/EP4721105A1/en).
- **US 2026/0252366 A1, “Automating Web-Based Tasks.”** This was a Phase 1/2 search lead. The cited identifier's bibliographic information and claims remain unverified from accessible primary-source text; no conclusion here depends on its scope.
- No granted patent's claims are relied on. The targeted search did **not** establish that no relevant patent exists. It did not verify claims about service-verifiable finality receipts, independent evidence provenance, or browser-action reconciliation.

### Technical papers

- **Dhulipala et al., “Step-Aligned Script Generation with Verification and Recovery for Web Automation Testing,” arXiv:2610.25601v1 (2026), especially Section V.** The paper's abstract and evaluation discuss step-level provenance, assertions/oracles, repair history, verification, and reversibility-aware backtracking for generated web-test scripts. It is close browser-recovery work, but does not establish whether a remote side effect committed after an ambiguous response. [arXiv record](https://arxiv.org/abs/2610.25601v1) · [HTML text](https://arxiv.org/html/2610.25601).
- **Zhou et al., “WebArena: A Realistic Web Environment for Building Autonomous Agents,” arXiv:2307.13854 (2023).** Relevant as a realistic web-agent environment and evaluation precedent, not as a finality mechanism. [arXiv record](https://arxiv.org/abs/2307.13854).

### Standards and ordinary engineering techniques

- **HTTP Semantics, RFC 9110 §9.2.2, “Idempotent Methods.”** Standard retry guidance distinguishes idempotent from non-idempotent methods and warns against automatically retrying a non-idempotent request without knowing its semantics or having a means to determine that the original was not applied. This is a protocol standard, not a patent. [RFC section](https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.2).
- **AWS Builders’ Library, “Making retries safe with idempotent APIs.”** The article describes caller-provided request identifiers and specifically notes that recording the token and performing mutations must be atomic to avoid token/effect divergence. This is ordinary service engineering and closely related to the idempotency condition in this model. [Article](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/).
- **AWS Prescriptive Guidance, “Transactional outbox pattern.”** Describes the dual-write failure between a database mutation and a message/event notification, and the outbox technique. This is adjacent durable intent/reconciliation engineering, not a browser action receipt. [Documentation](https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html).
- **PostgreSQL documentation, `PREPARE TRANSACTION`.** Documents prepare/commit/rollback prepared transactions under a transaction manager (two-phase commit). This can coordinate participating transactional resources, but a third-party web UI that does not join the transaction is outside that guarantee. [Documentation](https://www.postgresql.org/docs/current/sql-prepare-transaction.html).
- **Temporal documentation, “Events and Event History.”** Describes service-recorded workflow events and activity lifecycle/history. Workflow history supports durable orchestration and replay; it does not by itself prove that an external browser-side effect committed unless that service reports the outcome. [Documentation](https://docs.temporal.io/workflow-execution/event).

### Patent assessment and search gaps

The tested controller is a policy that consumes explicit service guarantees; it does not create those guarantees. Operation IDs, payload binding, authenticated receipts, terminal status, idempotency, durable journals, two-phase commit, outboxes, workflow histories, and reconciliation are established concepts. Phase 3 did not identify a technically distinct mechanism that survives comparison with those ordinary techniques. A local simulator cannot establish novelty, non-obviousness, claim scope, or patentability.

Unresolved search gaps include full claim-text and prosecution review for the cited applications, patent-family and status verification in official registers, claim searches across relevant jurisdictions, and a claim-by-claim comparison against a narrower technical contribution (if one is later identified). The available patent description passages are not a substitute for verified claims. Do not treat this report as legal advice or a recommendation to file.

## 10. Recommendation and next experiment

Do not advance the Phase 2 quorum-and-wait candidate. Do not advance Phase 3 as a patent concept based on these simulations. Retain the Phase 3 controller contract as a safety specification: when service guarantees are absent or evidence conflicts, do not claim completion and require reconciliation/human intervention.

Further engineering research is justified only if it can exercise a local service whose explicit contracts can be fault-injected and independently checked. A useful next experiment would implement a test service with a durable atomic idempotency ledger, authoritative terminal status, verifiable receipt generation, deliberate response loss, commit delay, cache lineage, and process restart. Compare the controller to service-native reconciliation and ordinary outbox/workflow mechanisms. Do not test against real transactions. If the service contract supplies all the value with standard mechanisms, stop the novelty/patent direction.

## 11. Reproduction and validation

From the project directory:

```powershell
.\.venv\Scripts\python.exe .\phase3_finality.py
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_phase3.py" -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Recorded validation for this revision:

- Phase 3 tests: **16 passed**.
- Full Phase 1–3 regression suite: **45 passed**, 0 failed.
- Phase 3 source/test compilation with `compileall`: **passed**.
- Phase 3 comparison: **15 scenarios × 20 repetitions × 5 policies = 1,500 policy-cases total**, with identical scenarios supplied to all policies.
- Comparison outputs are simulations; latency is modeled, and no real-world performance measurement was made.
