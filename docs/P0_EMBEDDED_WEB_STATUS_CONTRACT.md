# P0 embedded minimal web status contract

Status: implementation target for `P0_EMBEDDED_MINIMAL_WEB_STATUS`.

## Purpose

Prove the canonical one-binary composition can expose a minimal embedded/local web UI without introducing a second state model, remote-by-default service, or mutation authority.

The page is a presentation of the already-qualified read-only Doctor surface. It is not a management console.

## Surface

The executable adds:

```text
keelaryn web-status --control-dir <existing-protected-control>
                    [--listen 127.0.0.1:0]
```

Default listen address: `127.0.0.1:0`.

Only literal loopback IP addresses are accepted. Wildcard, LAN, hostname and other non-loopback listen values fail closed.

The command announces exactly one local URL after the listener is established, then serves until its context/process ends.

Endpoints:

- `GET /` — server-rendered embedded status page;
- `GET /api/status` — the same `doctor.Report` as JSON;
- `GET /assets/status.css` — embedded stylesheet.

`HEAD` is also allowed. Other methods are rejected.

## Authority and state

- `doctor.Run` remains the diagnostic authority.
- The handler resolves an existing protected control directory at construction and retains its physical path.
- Every status request performs fresh read-only diagnostics.
- No route creates, migrates, repairs, rebuilds or mutates control state.
- No route accepts corpus paths, database paths, provider credentials, search queries, mutation plans or arbitrary filesystem paths.
- No cookies, sessions, CORS grants, uploads or request-body APIs are introduced.
- HTTP status `200` means Doctor PASS; `503` means Doctor FAIL while still returning the diagnostic body.

## Network boundary

P0 is local-only:

- bind must be a literal loopback IP;
- the actual listener address is rechecked after bind;
- requests with a non-local Host header are rejected;
- browser Fetch Metadata is fail-closed for `cross-site` and `same-site` requests while direct navigation (`none`), same-origin requests, and non-browser clients without the header remain supported;
- no TLS/authentication design is claimed because remote access is not exposed;
- a future non-loopback/remote mode is a separate security boundary and requires its own explicit authentication/origin/TLS contract and audit.

Responses use no-store and restrictive browser security headers. No client-side script is required.

## Resource bounds

The server uses standard-library `net/http` with bounded header size and read/write/idle timeouts. Doctor verification has a 30-second context deadline and a single in-flight slot; overlapping status requests fail fast with HTTP 503 + `Retry-After` rather than creating concurrent full search-verification scratch copies. The UI contains only small assets embedded in the executable.

Doctor's existing read-only SQLite/FTS verification semantics remain authoritative; the web layer does not duplicate them.

## Qualification target

The stage is qualified only after:

1. handler tests prove page/API parity with Doctor;
2. protected state database bytes are unchanged by status requests;
3. non-local Host, cross-site/same-site browser fetches, and mutating methods fail closed;
4. non-loopback listen addresses fail closed;
5. a real ephemeral loopback listener starts and stops under context cancellation;
6. concurrent Doctor verification is bounded to one in-flight check with a bounded context;
7. CLI wiring supplies a signal-cancelled context and proves only `--control-dir` and loopback `--listen` are exposed;
8. Ubuntu and Windows exact-head CI/tests/vet pass;
9. exact-head semantic/security review is clean;
10. stage retrospective is recorded before final P0 proof re-audit.
