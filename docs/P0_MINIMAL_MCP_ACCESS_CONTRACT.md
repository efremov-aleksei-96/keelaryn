# P0 — Minimal MCP access contract

Date: 2026-10-02
Status: **IMPLEMENTATION CANDIDATE**

## Goal

Expose the already-qualified local read path to MCP clients without creating a new identity, storage, mutation, HTTP, authentication, or provider-authority layer:

```text
operator-selected local corpus + protected control directory
→ stdio MCP server
→ read-only search tool
→ read-only ContextBundle tool
→ existing qualified Search / ContextBundle runtime
```

The official `github.com/modelcontextprotocol/go-sdk` is the protocol implementation. The first qualified dependency target is v1.8.0.

## Authority boundary

Filesystem authority is fixed by the operator when the process starts:

```text
keelaryn mcp-stdio --root <corpus> --control-dir <protected-control-dir>
```

MCP tool arguments MUST NOT accept:

- corpus/root paths;
- control-directory paths;
- raw state/search database paths;
- provider credentials or tokens;
- arbitrary filesystem paths.

Therefore an AI client cannot use the MCP tool surface to retarget Keelaryn at another local path. Server construction resolves the same physical protected-scope boundary as the runtime and fails closed if the control directory is inside the corpus. Existing protected runtime checks remain authoritative for control-storage and current-corpus provenance.

The MCP read path is strictly read-only at the SQLite boundary as well as at the corpus boundary. State/search databases are opened with SQLite read-only handles plus `query_only`; the MCP path never creates, migrates, repairs or vacuums them. A database that still needs a schema/security upgrade fails closed until an explicit non-MCP preparation path completes that work.

## Tool surface

### `keelaryn_search`

Input:

- `query` — literal all-terms query, limited to 4096 UTF-8 bytes;
- optional `limit` — defaults to 20; the MCP surface rejects values outside 1…20.

Output:

- exact derived search hits preserving ArtifactID, RevisionID, extractor identity and ContentEvidence.

Execution delegates to the MCP-only strict reader `runtime/local.QueryProtectedReadOnly`. The previously qualified CLI `search` path retains its existing migration-capable behavior; this stage does not silently redefine that surface. Search remains rebuildable selection assistance and does not become identity or Locator authority.

### `keelaryn_context_bundle`

Input:

- `query` — limited to 4096 UTF-8 bytes;
- explicit `reason` — limited to 4096 UTF-8 bytes because it is carried on every selected item;
- optional `limit` — defaults to 20; the MCP surface rejects values outside 1…20;
- optional `max_bytes` — defaults to 4 MiB per selected file and cannot exceed 4 MiB;
- the server additionally enforces a fixed 4 MiB aggregate budget across extracted text in the whole ContextBundle. The remaining budget is applied before each source read; an item that cannot fit is returned as the existing bounded `LIMIT_EXCEEDED` outcome, while later smaller items may still fit.

Output:

- the existing ephemeral `ContextBundle`.

Execution delegates to the MCP-only strict reader `runtime/local.BuildProtectedContextReadOnly`. The previously qualified CLI `context-bundle` path retains its existing behavior; this stage does not broaden its semantics. The strict MCP path preserves the already-qualified gates:

- exact current Artifact+Revision match;
- supported extractor identity;
- exact provenance recheck;
- read-only source-boundary fingerprint proof before and after reads;
- fail-closed behavior on stale/non-current state.

## MCP semantics

Both tools are annotated read-only and closed-world.

The first surface uses **stdio only**. It does not expose HTTP, remote network listening, OAuth/authentication, prompts, resources, sampling, provider writes, corpus writes, or durable ContextBundle storage.

Tool execution errors are returned as MCP tool errors through the official typed-tool helper; they do not silently coerce invalid or stale state into successful output.

## Interruption and durability

The MCP server itself owns no durable state. Terminating or restarting it does not require recovery.

Search data remains rebuildable. ContextBundles remain ephemeral. Authoritative identity/revision/project state stays in the existing Keelaryn stores and contracts.

## Qualification targets

Before this slice can be marked qualified:

1. official Go MCP SDK dependency is locked and `go mod tidy -diff` is clean;
2. in-memory MCP protocol test lists exactly the intended tools;
3. tool schemas expose no root/control/raw database path arguments;
4. tool annotations are read-only and closed-world;
5. search returns exact Artifact/Revision provenance through MCP;
6. ContextBundle returns the same exact selected revision and source text through MCP;
7. CLI startup accepts only operator-scoped `--root` and `--control-dir`, and server construction rejects a control directory inside the corpus;
8. state/search database bytes remain unchanged across qualified read-only access and attempted writes fail closed;
9. MCP callers cannot expand the qualified request/result budget beyond 4096 UTF-8 bytes for query/reason fields, 20 selected hits, 4 MiB per selected file, or 4 MiB aggregate extracted text per ContextBundle;
10. existing full Go tests and vet pass on Ubuntu 24.04 and Windows 2025;
11. exact PR diff contains no corpus/provider mutation surface;
12. a stage retrospective/audit is completed before moving to embedded web status.
