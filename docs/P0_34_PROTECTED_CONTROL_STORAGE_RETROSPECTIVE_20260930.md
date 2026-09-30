# P0-34 — Protected control storage retrospective

Date: 2026-09-30  
Status: **QUALIFIED**

## Qualified product

- Product/qualification head: `6ade05b9595458693eea701091fd2aef54117f8b`
- Exact-head CI: `36670536752`
- Authority schema: v45
- Search schema: v3
- New module versions: none
- Corpus mutations: none
- Live provider: no

## Result

The supported local executable now derives state/search SQLite paths only from one protected `--control-dir`.

The qualified boundary covers:

- physical parent canonicalization before control-directory creation;
- lexical and physical rejection of control state inside the corpus;
- Unix owner-only directory protection;
- Unix control-file owner and hard-link escape checks;
- Windows native protected DACL creation and verification;
- explicit current-user owner on the Windows control directory;
- trusted-principal ACL verification for existing SQLite/control files;
- symlink/reparse-point rejection;
- SQLite main/journal/WAL/SHM namespace verification;
- post-operation re-verification before successful results are returned;
- removal of raw `--state-db` / `--search-db` from the executable surface.

## Qualification defect found and fixed

Run `36669415168` looked green in the GitHub API but its Windows log contained a real `go test ./...` failure. Two causes were corrected:

1. Windows SDDL omitted an explicit owner and the created control directory could receive the token default owner.
2. `go test` and `go vet` were in one PowerShell step, allowing a later successful native command to mask an earlier failing exit code.

The corrected workflow splits dependency lock, tests and vet into distinct steps. Exact-head run `36670536752` shows independent success for Windows `Go tests` and `Go vet`, plus Ubuntu and validate success.

The false-green run is permanently classified as invalid qualification evidence.

## Targeted retrospective

No new product BLOCKER/CRITICAL remains in the P0-34 scope after the S1-S5 security hardening and Q1 CI-gate correction.

`AUDIT_SECURITY_H3_STATE_DB_FILESYSTEM_PROTECTION` is resolved for the currently supported local executable runtime profile.

Android direct runtime remains separately unqualified under H2; P0-34 does not claim Android support.
