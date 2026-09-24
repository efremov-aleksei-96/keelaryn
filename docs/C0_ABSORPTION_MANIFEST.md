# C0 Legacy Absorption Manifest

This is migration evidence, not product architecture. `KEELARYN_CANONICAL.md` remains authoritative.

| Legacy source | Absorb into new Keelaryn | Leave behind |
| --- | --- | --- |
| `core/keelaryn_core/storage.py` | atomic temp/write/fsync/replace; verify-after-write; unsafe path/link rejection; durability-boundary fault injection | Hub MASTER/canonical layout |
| `drive_transaction.py` | capture prestate; exact identity revalidation; OLD/NEW/UNKNOWN classification; crash recovery; ambiguity blocks mutation | Hub publication model |
| `drive_mutation_gate.py` | mutation-boundary revalidation; fail closed | Hub workflow |
| `drive_recovery_block.py` | explicit recovery-required state; no blind retry | Hub states |
| `operation_runtime.py` | immutable terminal result; mutation phase journaling; interruption reconcile | transport/agent dispatcher |
| old fault/invariant tests | fault injection at durability boundaries; invariant-first testing | obsolete Hub assertions |
| Manager release engineering | one captured source snapshot; deterministic artifacts; validate before publish; authority/manifest last | historical package format |
| Manager test framework | disposable test roots; verify archive before deletion; hash manifests; unsafe-link rejection | Manager gate implementation |
| Manager privacy | strict release allowlist; never absorb personal corpus/private runtime into generic distribution | Hub-specific exclusions |
| Manager onboarding/UI | nontechnical guided setup; damaged-state recovery instead of destructive reinit; plan before confirm | PowerShell/menu code |
| r0007-r0009 incidents | frozen candidate immutability; reconcile external authority; distinguish durable commit from failed post-verification | candidate workflows/control plane |
| CorpusBootstrap | current owner beats legacy copy; migration provenance; no destructive cleanup; user folder profile != Core ontology | maintainer-specific taxonomy as universal product |

Future Go regression families must cover these guarantees when the corresponding subsystem exists: interruption at durability boundaries; identity change at mutation boundary; ambiguity; copy vs move; rename continuity; unchanged idempotence; derived rebuild identity stability; unsafe traversal; release privacy; post-commit verification interruption.
