# P0 minimal read-only MCP access retrospective — 2026-10-02

## Boundary

Merged product head: `84fc28d11184adb45e8bb3a1b7a7cfb226371226`.

Qualified source head: `da3e429100d9fa0ecc5dba9cfa31c35b04377d15`.

The merged commit and qualified source head have the identical Git tree `b105e38b81209f19bf4a7d288a9241922f914dc4`; the squash merge therefore changed commit history only, not qualified product bytes.

Exact-head qualification: GitHub Actions run `37037679567` — validate, Ubuntu 24.04 tests/vet, and Windows 2025 tests/vet all PASS.

Final Codex review on `da3e429100d9fa0ecc5dba9cfa31c35b04377d15`: **clean — no major issues found**.

Result: **PASS — minimal read-only MCP access qualified; zero open review findings; embedded minimal web status is next.**

This is a stage-scoped retrospective and P0 closure-ledger reconciliation. It is not the final P0 proof re-audit.

## Qualified product surface

The stage adds a minimal local MCP server over the official Go SDK:

- transport: stdio only;
- tools: `keelaryn_search` and `keelaryn_context_bundle`;
- no MCP resource, prompt, sampling, filesystem-path, raw-database-path, provider-write, corpus-write, or state-mutation authority;
- operator fixes corpus root and protected control directory at process startup;
- request fields and result/file-read budgets are bounded;
- search results return exact Artifact/Revision provenance;
- ContextBundle remains ephemeral and re-proves current corpus bytes/provenance before returning text.

No network listener is introduced by this gate.

## Architecture and correctness review

The MCP layer does not become identity authority. Durable identity and provenance remain in protected `state.db`; `search.db` remains rebuildable derived state.

Search schema v4 adds a rebuildable `SourceBoundary` binding the complete search cache to the exact local provider/root/scan/bootstrap fingerprint that produced it. Full cache replacement and its boundary commit atomically. MCP startup verifies protected state, the exact durable bootstrap receipt, derived-cache SourceBoundary, SQLite/foreign-key integrity, FTS integrity, and control-storage protection before advertising tools.

Per-request MCP search reads SourceBoundary and FTS hits inside one SQLite read transaction/snapshot, then re-reads authoritative state after the search and requires the state boundary to be unchanged. This closes the concurrent cache-rebuild/state-advance window without relying on a process-local lock.

The ContextBundle MCP path uses the same bound search semantics. It also pins a physical corpus read root at startup while retaining the original authority root for state lookup, so relative paths or later ancestor-symlink retargets cannot redirect corpus reads. Current corpus bytes are still re-proved before and after bundle construction.

FTS5's write-shaped integrity command never runs on the protected source database. Verification copies the index into an ephemeral on-disk scratch database created with the same platform-specific protected-directory and protected-file checks as control storage; this avoids both full-index RAM amplification and permissive temp-directory leakage.

## Resource and authority bounds

The qualified surface enforces:

- at most 20 search/context selections;
- at most 4 MiB per selected file;
- at most 4 MiB aggregate extracted ContextBundle text;
- at most 4096 UTF-8 bytes for MCP query and reason fields;
- no caller-controlled root/control/state/search paths;
- no durable writes from MCP handlers;
- no remote HTTP listener in this stage.

The aggregate ContextBundle budget is applied before each source read rather than truncating after serialization.

## Findings closed during the stage

Review and Sol audit found and closed the following material classes before qualification:

1. unbounded aggregate ContextBundle response accumulation;
2. incomplete MCP startup validation of state/root/bootstrap and FTS integrity;
3. rebuildable search cache not durably bound to authoritative state;
4. in-memory full-index FTS verification resource amplification;
5. on-disk verification scratch not initially protected to control-storage standards;
6. verify-then-search TOCTOU across concurrent search-cache replacement;
7. ContextBundle using an unbound search path;
8. startup path pinning ambiguity across relative paths/filesystem aliases;
9. Windows false rejection caused by treating normal temp-path aliasing as invalid instead of pinning the physical read root.

All review threads are resolved on the qualified head. The final exact-head Codex re-review reported no major issues.

## Cross-platform qualification

Run `37037679567` on `da3e429100d9fa0ecc5dba9cfa31c35b04377d15`:

- validate — PASS;
- Ubuntu 24.04 dependency lock — PASS;
- Ubuntu Go tests — PASS;
- Ubuntu Go vet — PASS;
- Windows 2025 dependency lock — PASS;
- Windows Go tests — PASS;
- Windows Go vet — PASS.

The Windows regressions cover the platform-specific protected ACL path and the physical-root pinning behavior.

## Reuse review

The implementation reuses `github.com/modelcontextprotocol/go-sdk v1.8.0` rather than implementing JSON-RPC/MCP framing. The official release remains the latest reviewed stable release as of 2026-10-02 and includes transport resource-exhaustion hardening.

The stage also reuses existing Keelaryn search, ContextBundle, protected control storage, SQLite read-only validation, corpus snapshot/fingerprint, and Artifact/Revision provenance semantics. No parallel identity model, vector database, content mirror, or new persistence backend was introduced.

External reference reviewed 2026-10-02:

- https://github.com/modelcontextprotocol/go-sdk/releases/tag/v1.8.0

## Carried findings

This stage does not resolve or reclassify the existing non-MCP findings:

- `AUDIT_RELEASE_H1_STATE_DB_ROLLBACK_NOT_IMPLEMENTED` — carried HIGH, release/update gate;
- `AUDIT_RELEASE_H2_ANDROID_QUALIFICATION_ABSENT` — carried HIGH, portability gate;
- `AUDIT_P0_36C_TOKENINFO_SCOPE_PREFLIGHT_AVAILABILITY` — carried MEDIUM, reassess at final P0 proof / production live-provider boundary.

No new BLOCKER/CRITICAL finding remains open from the MCP stage.

## Remaining P0 gates

1. **Embedded minimal web status.**
2. **Final P0 proof re-audit.**

P0 is not closed. The next autonomous product boundary is **embedded minimal web status**. It should remain a minimal local status/diagnostic surface, reuse existing Doctor/status authority, avoid introducing a second state model, and fail closed on any network/exposure ambiguity.
