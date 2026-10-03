# P0 embedded minimal web status retrospective — 2026-10-03

## Boundary

Merged authoritative head: `b7858176fe64d98b45e3118e5b1dfad44e64d9cb`.

Qualified source head: `187451d71f728df9ac724fd8752a078c52824b0c`.

Exact-source qualification: GitHub Actions run `37114259657` — validate, Ubuntu 24.04, and Windows 2025 all PASS.

The seven files changed by the embedded-web-status stage have identical Git blob SHAs at the qualified source head and the merged authoritative head. The merged head additionally contains only the already-qualified continuation-profile governance work from PR #74; that governance PR passed run `37113404716`.

Final Sol semantic/security review on the qualified web-status head: **clean — zero open review threads and no remaining material network, concurrency, shutdown, or mutation-authority finding**.

Result: **PASS — embedded minimal web status qualified and merged; final P0 proof re-audit is next.**

This is a stage-scoped retrospective. It does not itself close P0.

## Qualified product surface

The executable now exposes:

```text
keelaryn web-status --control-dir <existing-protected-control>
                    [--listen 127.0.0.1:0]
```

The surface is deliberately local and read-only:

- default bind is `127.0.0.1:0`;
- only literal loopback IP listeners are accepted;
- the actual bound listener is rechecked as loopback;
- only `GET` and `HEAD` are accepted;
- routes are limited to `/`, `/api/status`, and the embedded stylesheet;
- `doctor.Run` remains the sole diagnostic authority;
- no route accepts corpus paths, raw database paths, credentials, search queries, uploads, mutation plans, or request-body APIs;
- no cookies, sessions, CORS grants, or mutation endpoints are introduced;
- Doctor PASS maps to HTTP 200 and Doctor FAIL maps to HTTP 503 while preserving the diagnostic response body.

## Network and browser boundary

The stage fails closed on network exposure ambiguity:

- wildcard, LAN, hostname, and other non-loopback listen values are rejected;
- non-local Host headers are rejected;
- browser Fetch Metadata rejects `cross-site` and `same-site` requests;
- same-origin, direct navigation (`none`), and non-browser clients without Fetch Metadata remain supported;
- no remote TLS/authentication claim is made because no remote mode exists in this stage;
- responses use `no-store`, restrictive CSP, no-referrer, nosniff, and frame denial.

Any future non-loopback mode remains a separate security boundary requiring an explicit authentication/origin/TLS contract and a new audit.

## Resource and shutdown bounds

Doctor verification may copy and validate rebuildable search state, so the web layer bounds this work explicitly:

- at most one Doctor verification is in flight;
- overlapping diagnostic requests fail fast with HTTP 503 and `Retry-After: 1`;
- each diagnostic receives a 30-second context deadline;
- the server write timeout is 40 seconds, preserving a 10-second response margin after the diagnostic deadline;
- request contexts derive from the server context;
- CLI execution uses a SIGINT/SIGTERM-cancellable context;
- shutdown cancellation reaches active Doctor work;
- if graceful shutdown exceeds its grace window, the server is closed;
- `Run` waits for the diagnostic slot to become idle before returning, so protected verification scratch cleanup completes.

## Findings closed during the stage

Review found and the qualified head closed these material classes:

1. unbounded concurrent Doctor verifications creating multiple full-size scratch copies;
2. process signals not reaching the server shutdown path;
3. HTTP write timeout expiring at the same boundary as the Doctor diagnostic deadline;
4. shutdown timeout not explicitly cancelling active diagnostic request contexts before return;
5. browser local-status requests accepting `same-site` Fetch Metadata instead of failing closed;
6. incomplete HEAD/failure-response regression coverage.

All associated review threads are resolved on PR #73.

## Cross-platform qualification

Run `37114259657` on `187451d71f728df9ac724fd8752a078c52824b0c`:

- validate — PASS;
- Ubuntu 24.04 — PASS;
- Windows 2025 — PASS.

The merged authoritative head preserves the exact stage blobs:

- `cmd/keelaryn/main.go` — identical;
- `cmd/keelaryn/main_test.go` — identical;
- `docs/P0_EMBEDDED_WEB_STATUS_CONTRACT.md` — identical;
- `internal/webstatus/static/status.css` — identical;
- `internal/webstatus/static/status.html` — identical;
- `internal/webstatus/webstatus.go` — identical;
- `internal/webstatus/webstatus_test.go` — identical.

PR #74's governance-only changes were independently qualified by run `37113404716` before merge.

## Authority and architecture review

The web surface does not become a second state model. It renders the existing Doctor result over an embedded presentation layer and performs no durable state mutation.

Protected control-storage validation remains in the existing control/storage and Doctor paths. The web layer neither bypasses those checks nor invents an alternate health/status authority.

No new persistent database, identity model, provider integration, background service, remote listener, or credential store is introduced.

## Carried findings

This stage does not resolve or reclassify the existing non-web findings:

- `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — carried HIGH;
- `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — carried HIGH;
- `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` — carried MEDIUM.

No new BLOCKER or CRITICAL finding remains open from the embedded web-status stage.

## Remaining P0 gate

1. **Final P0 proof re-audit.**

The final re-audit must reassess the current authoritative tree from scratch against the full P0 proof dimensions, including architecture authority, state/provenance boundaries, read-only surfaces, release/rollback carry findings, portability evidence, and closure-ledger consistency. P0 remains open until that audit is complete.
