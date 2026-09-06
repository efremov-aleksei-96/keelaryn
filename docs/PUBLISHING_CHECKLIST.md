# Public publishing checklist

## Source / privacy

- [ ] `tools/Verify-PublicRepository.ps1` passes on Windows PowerShell 5.1.
- [ ] `manager/` matches `product/install/INSTALLATION.json` exactly.
- [ ] `manager/state/` is absent.
- [ ] `hub/` contains only its boundary README.
- [ ] `tests/work` and `tests/results` contain only their committed README placeholders.
- [ ] no CURRENT/CANDIDATE/APPROVED/UPDATE ZIP or candidate-transport JSON is committed.
- [ ] no user-profile path, credential/private-key material or instance artifact ID is present.
- [x] MIT license is present.

## Release evidence

- [ ] public Manager version corresponds to a production-qualified release.
- [ ] latest local Full Gate passed with frozen qualified Gate Framework.
- [ ] `PUBLIC_PROVENANCE.json` matches the published Manager/framework identities.
- [ ] `PUBLIC_FILE_MANIFEST.json` exact source-file hashes match.

## Git integrity

- [ ] clone/checkout with `core.autocrlf=true` leaves all 61 Manager managed files byte-identical.
- [ ] frozen framework files remain byte-identical.
- [ ] `.gitattributes` continues to mark authoritative Manager/Framework source as `-text`.

## CI

- [ ] Windows hosted CI passes repository verifier.
- [ ] Windows hosted CI generates the gate with frozen framework.
- [ ] SourceGate passes.

Hosted CI does not replace the local Full Gate.

## Repository settings

Recommended:

- protect `main`;
- require the Windows source-validation workflow before PR merge;
- enable private vulnerability reporting;
- prefer squash merges for milestone syncs;
- do not commit generated release artifacts.
