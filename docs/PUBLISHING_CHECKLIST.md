# Public publishing checklist

This candidate is designed to be safe for GitHub review, but public publishing should still be deliberate.

## Required before first public push

- [ ] Run `tools/Verify-PublicRepository.ps1` on Windows PowerShell 5.1.
- [ ] Run the full local Windows parser/SelfTest/release gate.
- [ ] Run the GitHub Actions workflow manually only for a publication/milestone checkpoint.
- [ ] Confirm `hub/` contains only its boundary README.
- [ ] Confirm `tests/work` and `tests/results` contain no generated private evidence.
- [ ] Confirm no CURRENT/CANDIDATE/APPROVED ZIP or candidate transport JSON is present.
- [x] Repository license selected: MIT.
- [ ] Review the public README and PORTFOLIO claims against current verified release evidence.

## License

The public repository uses the **MIT License**. `LICENSE` is part of the committed public tree and must remain present in published snapshots.

The license covers the source and documentation actually committed to this public repository. It does not imply publication or licensing of personal Hub instance data, credentials, local runtime state, private CURRENT/CANDIDATE/APPROVED packages, or other uncommitted material.

## Git checkout integrity

- [x] Public candidate tested with `core.autocrlf=true`: all 57 Manager managed files remain byte-identical after Git round-trip.
- [x] `manager/_manager_version.txt` is explicitly pinned to LF in `.gitattributes`.

## CI and publication cadence

GitHub is not the development test runner for Keelaryn. Candidate iteration, profiling, fault injection and disposable update gates stay local under `tests/work` and durable results stay under the local `tests/results` boundary.

The checked-in Windows workflow uses only `workflow_dispatch`; pushes and pull requests do not start hosted runners automatically. Run it manually after a batched milestone is ready for publication. The workflow intentionally does not upload Actions artifacts.

Recommended cadence:

- do not push rejected candidates or every Manager patch version;
- batch several locally verified changes into one public milestone;
- validate locally before pushing;
- run hosted CI once for the milestone, not once per development commit;
- prefer a public repository for the published portfolio once it is ready; keep private staging CI manual-only.

## Recommended repository settings

- enable branch protection for the default branch;
- require the Windows validation workflow before merge;
- enable private vulnerability reporting if available;
- avoid uploading generated release artifacts to Git unless a release page intentionally needs them;
- keep real Hub data in a separate non-repository location.
