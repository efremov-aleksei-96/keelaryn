# Keelaryn — Manager Development

This optional Project is for development of Keelaryn Manager and its supporting engineering infrastructure. It is not required for a normal Keelaryn user.

## Scope

Work on:

- Manager architecture and PowerShell runtime;
- performance and context optimization;
- security and threat modeling;
- update, rollback and migration mechanisms;
- Doctor, SelfTest and validation;
- SOURCE / DISTRIBUTION / UPDATE / AI_CONTEXT builds;
- release engineering and reproducibility;
- Windows compatibility and regression testing;
- public GitHub repository, CI and release pipeline;
- provenance and supply-chain identity;
- generic/public distribution and onboarding;
- system-level defects escalated from Workspace, Chats or Chat Manager.

## Development priorities

1. correctness;
2. no regression of existing capabilities;
3. data safety and rollback;
4. deterministic behavior;
5. security;
6. performance;
7. reduced ChatGPT context requirements;
8. maintainability.

Fresh validation remains mandatory at transaction/commit boundaries.

## Canonical layout

```text
keelaryn/
├── manager/
├── hub/
└── tests/
```

Use lowercase component directory names.

The personal production Hub is not Manager development source code. Use sanitized fixtures or disposable copies for testing Hub behavior.

## Fresh continuation input

Attach the newest explicitly issued Manager Development handoff, then only the task-specific engineering context needed for the next work item.

Prefer AI_CONTEXT and exact source routes over repeatedly loading the entire Manager runtime.

## Version and qualification discipline

Never silently modify an already issued candidate after a defect is found.

Use:

- a new Manager version/candidate when product bytes change;
- a new gate revision when only qualification execution/evidence changes;
- a new framework revision only when reusable Gate Framework source changes.

Do not rewrite historical qualification provenance.

Production approval requires all applicable static, parser, SelfTest, deterministic build, disposable update/migration/rollback, Doctor, production-immutability, CI and exact-artifact-identity gates.

## Windows gate convention

Normal Windows Manager gate archives are named:

```text
manager-<version>.zip
```

and use the established `UNPACK_MANAGER_GATE.cmd` workflow.

## Output

Development artifacts and handoffs may be saved under:

```text
exchange\chatgpt\development
```

Do not place personal Hub content in generic SOURCE, DISTRIBUTION, UPDATE, AI_CONTEXT, public GitHub or generic fixtures.