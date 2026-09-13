# Manager Engineering Knowledge

This directory is the repository-resident engineering memory for Keelaryn Manager.

It is intentionally split from historical CI logs and release evidence. The knowledge layer stores compact, stable engineering facts that can be selected by changed files/functions and rendered into a task-specific risk context without loading full Manager history into ChatGPT.

## Layers

- `root-causes.json` — normalized defect/root-cause classes.
- `defects/manager-4.17.x.json` — canonical product/system defects and material process escapes from the 4.17.x convergence line.
- `invariants/multi-hub.json` — architectural invariants. Invariants are stronger than individual regressions.
- `state-machines/multi-hub.json` — executable scenario/operation expectation rules.
- `risk-map.json` — source surface -> invariant/root-cause/regression/state-machine mapping.

Historical qualification evidence stays in PRs, commits, workflow runs, artifacts, provenance refs and dedicated evidence files. Knowledge records contain identities/references only; they must not embed large logs or personal Hub content.

## Required relation

Every significant product defect follows:

`defect -> root-cause class -> violated invariant -> permanent coverage`

A fixed defect must point to permanent executable/static coverage. An open release blocker may point to planned coverage, but the pre-freeze Risk/Defect Gate must fail while the blocker remains open.

## Tooling

- `tools/Test-ManagerEngineeringKnowledge.ps1` validates references, coverage and state-machine completeness.
- `tools/Build-ManagerRiskContext.ps1 -BaseCommit <sha> -HeadCommit <sha>` derives changed files/functions and writes compact `MANAGER_RISK_CONTEXT.md` plus JSON.
- `tools/Invoke-ManagerRiskDefectGate.ps1` is the strict pre-freeze gate. It validates knowledge, builds the exact diff risk context, rejects unresolved release blockers, requires coverage for touched invariants, and runs applicable executable regressions.

Knowledge integrity is allowed to PASS before open product blockers are fixed. The strict Risk/Defect Gate is not: that distinction prevents the knowledge-bootstrap work itself from being blocked while preserving fail-closed candidate freeze discipline.

## Privacy boundary

Never include personal production Hub content in this layer. Sanitized identities such as Manager version, commit, PR, review thread, workflow run, artifact ID/hash and generic Hub-state descriptions are allowed only when required for engineering provenance.
