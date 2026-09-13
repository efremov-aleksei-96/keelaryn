# Manager Engineering Knowledge

This directory is the repository-resident engineering memory for Keelaryn Manager.

It is intentionally split from historical CI logs and release evidence. The knowledge layer stores compact, stable engineering facts that can be selected by changed files/functions and rendered into a task-specific risk context without loading full Manager history into ChatGPT.

Repository bootstrap is split deliberately:

- `MANAGER_DEVELOPMENT_STATE.json` at repository root is the machine-readable **volatile operational state**: authoritative development branch, stable lineage identities, open blockers, qualification summary and next exact goal. It never stores a self-referential current HEAD; clients resolve the authoritative branch ref live from GitHub.
- `MANAGER_ENGINEERING_ROADMAP.md` at repository root is the **deferred architectural backlog**: future ideas, priorities, dependencies, safety constraints and revisit/exit conditions. It is not release state.
- `tests/knowledge/**` is the **stable engineering knowledge layer** used for invariant/risk selection and pre-freeze enforcement.

## Layers

- `root-causes.json` — normalized defect/root-cause classes.
- `defects/*.json` — canonical product/system defects and material process escapes.
- `invariants/multi-hub.json` — architectural invariants. Invariants are stronger than individual regressions.
- `state-machines/multi-hub.json` — executable scenario/operation expectation rules.
- `risk-map.json` — source surface -> invariant/root-cause/regression/state-machine mapping.
- `audits/*.json` — bounded systemic audits that bind open blockers and required scenarios to the state machine before product convergence work.

Historical qualification evidence stays in PRs, commits, workflow runs, artifacts, provenance refs and dedicated evidence files. Knowledge records contain identities/references only; they must not embed large logs or personal Hub content.

## Required relation

Every significant product defect follows:

`defect -> root-cause class -> violated invariant -> permanent coverage`

A fixed defect must point to permanent executable/static coverage. An open release blocker may point to planned coverage, but the pre-freeze Risk/Defect Gate must fail while the blocker remains open.

Open release blockers recorded in engineering knowledge must remain synchronized with `MANAGER_DEVELOPMENT_STATE.json`. Risk audits must reference valid defects/invariants/state-machine states and operations; applicable audit scenarios are selected into task risk context through the winning state-machine rules for touched risk surfaces.

## Tooling

- `tools/Test-ManagerEngineeringKnowledge.ps1` validates root causes, invariants, defect references, state-machine completeness, risk mappings, audit references/scenarios and repository development-state consistency.
- `tools/Build-ManagerRiskContext.ps1 -BaseCommit <sha> -HeadCommit <sha>` derives changed files/functions and writes compact `MANAGER_RISK_CONTEXT.md` plus JSON, including applicable audit scenarios.
- `tools/Invoke-ManagerRiskDefectGate.ps1` is the strict pre-freeze gate. It validates knowledge, builds the exact diff risk context, rejects unresolved release blockers, requires coverage for touched invariants, and runs applicable executable regressions.

Knowledge integrity is allowed to PASS before open product blockers are fixed. The strict Risk/Defect Gate is not: that distinction prevents the knowledge-bootstrap work itself from being blocked while preserving fail-closed candidate freeze discipline.

## Autonomous continuation contract

Ordinary future Manager-development sessions should not require a manually reconstructed chat handoff. They should:

1. read `MANAGER_DEVELOPMENT_STATE.json`;
2. resolve its `authoritative_branch` HEAD live from GitHub and treat the remote branch as authoritative;
3. read the roadmap only when deferred priorities/architecture are relevant;
4. load exact task risk context and focused source instead of full history where possible;
5. update the development-state file whenever blocker set, lifecycle, qualification summary or next exact goal materially changes.

## Privacy boundary

Never include personal production Hub content in this layer, the development-state file, the roadmap, CI fixtures or public GitHub. Sanitized identities such as Manager version, commit, PR, review thread, workflow run, artifact ID/hash and generic Hub-state descriptions are allowed only when required for engineering provenance.
