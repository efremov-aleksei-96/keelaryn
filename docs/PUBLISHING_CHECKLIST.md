# Public publishing checklist

This checklist is for public repository/release preparation. Stable engineering rules live in the repository governance and Manager release contracts; volatile current identities are read from generated metadata rather than copied into this document.

## Source / privacy boundary

- [ ] `tools/Verify-PublicRepository.ps1` passes on Windows PowerShell 5.1.
- [ ] `manager/` matches `product/install/INSTALLATION.json` exactly.
- [ ] `manager/state/` is absent from public source.
- [ ] public `hub/` contains only its boundary material, not a real instance.
- [ ] committed `tests/work` and `tests/results` contain no private/local qualification evidence.
- [ ] no generated CURRENT/CANDIDATE/APPROVED/UPDATE ZIP or candidate-transport JSON is committed accidentally.
- [ ] no credential, private-key, recovery material or personal Hub data is present.
- [ ] generic Hub starter/governance fixtures remain sanitized product material.
- [ ] MIT license is present.

## Presentation integrity

- [ ] `tools/Verify-PublicPresentation.ps1` passes.
- [ ] README leads with the automation/state-management engineering problem rather than personal knowledge-management framing.
- [ ] current Manager/framework identities are not duplicated manually in landing/presentation prose.
- [ ] current release links resolve through GitHub `releases/latest` and current identity through `PUBLIC_PROVENANCE.json` / `PUBLIC_FILE_MANIFEST.json`.
- [ ] evidence links in README and portfolio documents resolve to public files/directories.
- [ ] historical version numbers appear only where they are part of evidence-backed history, not as volatile “current” claims.
- [ ] architecture/release diagrams still match the implemented trust boundaries.

## Release evidence

- [ ] `PUBLIC_PROVENANCE.json` identifies the intended production-qualified Manager and Gate Framework.
- [ ] `PUBLIC_FILE_MANIFEST.json` reproduces from authoritative Manager/Framework source.
- [ ] production Full Gate evidence for the release candidate passed all applicable phases.
- [ ] production Doctor passed.
- [ ] production UX smoke passed where required.
- [ ] exact tested UPDATE SHA-256 matches the provenance/public-release contract.
- [ ] personal Hub and runtime/local evidence remain excluded from public source/release assets.

## Git checkout / source-byte integrity

- [ ] authoritative Manager source remains byte-preserving under the repository `.gitattributes` contract.
- [ ] frozen Gate Framework source remains byte-preserving.
- [ ] `tools/Build-PublicFileManifest.ps1 -Check` passes after checkout.
- [ ] no repo-only presentation/governance change is misrepresented as a new Manager qualification.

## CI / pull-request gates

Every PR to `main` must satisfy the repository ruleset's required checks:

- [ ] `source-gate` PASS;
- [ ] `repository-governance` PASS;
- [ ] `release-policy` PASS.

When the PR is release-critical:

- [ ] `distribution-gate` ran on the exact PR head SHA;
- [ ] `release-policy` observed and accepted that exact `distribution-gate` result.

When Manager bytes or remote-qualification infrastructure changed:

- [ ] the hosted `disposable-full-gate` ran and its evidence was reviewed;
- [ ] disposable evidence remains classified as prequalification only;
- [ ] any required real production qualification cycle is still performed separately.

## Repository governance / supply chain

- [ ] `tools/Verify-RepositoryGovernance.ps1` passes.
- [ ] `tools/Verify-GitHubActionsPolicy.ps1` passes.
- [ ] `main` remains protected by the named active ruleset with no bypass actors.
- [ ] squash remains the only merge method.
- [ ] required status checks remain strict/up-to-date.
- [ ] external Actions remain pinned to full commit SHAs and within the explicit allowlist.
- [ ] GitHub-hosted jobs use approved explicit OS-family runner labels rather than `*-latest`.
- [ ] default workflow permissions remain read-only except the documented publication boundary.

## Publication

For a new applicable Manager release:

- [ ] release tag/version agrees with qualified provenance.
- [ ] GitHub Release is populated as a draft before publication.
- [ ] all expected assets are present and hash-consistent before publish.
- [ ] the newly published release is native-immutable.
- [ ] release attestation verification passes.
- [ ] every applicable asset attestation verifies.
- [ ] re-downloaded release assets are byte-identical to the gated artifacts.
- [ ] no already-published release/tag/history was rewritten to make a newer gate/framework result look historical.

## Cycle close

- [ ] merged service/development branch cleanup follows `REPOSITORY_GOVERNANCE.json`.
- [ ] unique candidate/gate/framework/release qualification refs are preserved.
- [ ] final public README, portfolio links and latest release page are checked from the merged `main` state.
