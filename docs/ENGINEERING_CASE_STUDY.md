# Engineering case study

Keelaryn evolved from practical Windows automation into a governed stateful system. The useful engineering story is not the feature count; it is how repeated failure modes changed the architecture, test strategy and release process.

Development priorities are ordered: **correctness → regression prevention → data safety/rollback → deterministic behavior → security → performance → reduced AI context → maintainability**.

## 1. Stateful updates became transactions

### Problem

A Manager update changes executable product bytes inside an installation that also contains user-owned state, bindings, history and a live Hub. A normal “copy new files over old files” approach cannot answer what happens after a partial failure.

### Design response

The update path was made transactional:

- validate the package envelope and declared managed set;
- stage candidate bytes away from the installed Manager;
- snapshot the existing installation for rollback;
- perform fresh validation at the transaction boundary;
- install the new managed set;
- run post-install validation;
- restore from the snapshot on failure.

### Validation response

The Full Gate does not treat rollback as documentation. It performs **fault injection** during Manager update, requires the update attempt to fail, verifies the rollback snapshot contract and then runs SelfTest on the restored baseline. A separate phase performs the real disposable native update and verifies Hub/CURRENT/binding preservation.

### Lesson

For stateful local automation, recovery is part of the write operation, not an optional troubleshooting procedure.

## 2. Deterministic builds required isolated roots

### Problem

A release builder can appear deterministic if two builds reuse the same workspace. Cached/intermediate state can hide dependencies on the build location or previous output.

A later release-engineering failure exposed nondeterministic UPDATE bytes only after the gate moved the two release builds into isolated roots. The defect was traced to transition bootstrap content that had captured a build-root-specific path during packaging.

### Design response

SourceGate now builds release artifacts from independent roots and compares the resulting identities. SOURCE, DISTRIBUTION, UPDATE and AI_CONTEXT are validated as products of managed source, not of one lucky filesystem layout.

### Lesson

“Build twice” is weaker than **“build twice from isolated state.”** Reproducibility tests need to remove the hidden state they are trying to detect.

## 3. Rejected candidates stay rejected

Keelaryn uses candidate immutability as release discipline: once candidate bytes have been issued for qualification, a discovered product-byte defect produces a new Manager version rather than silently changing the old candidate.

A concrete public example is the transition from **4.14.0 to 4.14.1**. The corrective release commit explicitly records that 4.14.0 was rejected and that 4.14.1 bound AI_CONTEXT runtime text to the exact file hash before qualification and publication.

Evidence: [`67d9c2b1`](https://github.com/efremov-aleksei-96/keelaryn/commit/67d9c2b1d96b27ba8291a61c33cd414a0afa73af).

### Lesson

Qualification history is useful only if the identity being discussed is stable. Rewriting a failed candidate would make later “PASS” evidence ambiguous.

## 4. Production data is a compatibility boundary, not a test fixture

### Problem

A real Hub is the best source of production compatibility information, but it is also user-owned state. Using it as a mutable test target would turn qualification into a data-safety risk.

### Design response

The Full Gate treats production Manager/Hub/CURRENT paths as read-only preflight inputs and performs mutable work under disposable `tests` roots. It snapshots production-visible identities, executes the regression suite elsewhere and verifies production immutability at the end.

Hosted remote prequalification goes further: it uses a **synthetic Hub created through Genesis**, so no personal Hub data is required at all.

### Lesson

The safest test double for a stateful workload is often a disposable copy or generated instance, while production contributes only the minimum read-only compatibility facts required by the gate.

## 5. AI_CONTEXT solved a context-cost problem without becoming a second codebase

### Problem

Loading the full Manager runtime into an AI development conversation is expensive, but hand-maintained summaries can drift from the implementation they describe.

### Design response

AI_CONTEXT is generated from managed source and provides task-specific routes plus exact source/function slices. The artifact is tied to exact runtime/source identity and validated during release construction.

The rejected 4.14.0 candidate is important here: reducing context was not accepted at the cost of ambiguous runtime provenance. The corrective release tightened the binding instead of treating the generated context as “close enough.”

### Lesson

Context optimization is safe only when the compressed/decomposed representation remains **lossless, reproducible and identity-bound**.

## 6. Windows filesystem behavior is part of the input model

Windows packaging and update paths have to account for behavior that generic happy-path ZIP code often ignores:

- `..` traversal and absolute/unsafe extraction paths;
- Windows reserved device names;
- case-insensitive and Unicode-normalization collisions;
- reparse points;
- file sharing violations and transient locks;
- path safety when moving between source, staging and installed trees.

The gate contains negative tests for archive traversal and other orchestration failure paths. The reusable Gate Framework also self-tests its sharing-violation retry behavior on real Windows semantics.

### Lesson

Platform edge cases are not “rare” when a tool's job is to move and replace files safely. They are part of the contract.

## 7. Test infrastructure became a separate trust boundary

### Problem

A candidate can only be trusted as far as the gate that declares it healthy. If Manager changes and test-harness changes are mixed casually, a passing result may say more about the modified test than about the candidate.

### Design response

The reusable Gate Framework has its own revision/qualification lifecycle. Manager candidate identity, gate revision and framework revision are separate. Disposable CI also refuses mixed Manager + framework changes.

The public provenance records the framework used for production qualification instead of silently reinterpreting old releases through newer test code.

### Lesson

A release gate is production infrastructure. It needs provenance and change discipline of its own.

## 8. Remote qualification reduced manual Windows dependency without weakening approval

A later workflow problem was operational rather than algorithmic: deep Windows testing should not require the maintainer to sit at a Windows workstation for every iteration.

The solution was a GitHub-hosted disposable Full Gate on a pinned Windows runner. It creates a synthetic canonical installation, runs the frozen gate and publishes machine-readable evidence. That evidence explicitly says:

- synthetic/disposable only;
- no personal Hub used;
- not production-qualified;
- real production validation still required.

This preserved the existing trust model while moving most defect discovery to unattended Windows execution.

See [Remote qualification](REMOTE_QUALIFICATION.md).

## 9. Performance work stays subordinate to correctness

Profiling has been used to separate expensive operations rather than optimizing by intuition. One example replaced only SHA-256 digest-to-hex formatting with a .NET `BitConverter` path while preserving digest inputs and output identity. Windows PowerShell 5.1 qualification measured approximately:

- **-7.8% total Doctor time**;
- **-32.3% portable-analysis time**;
- **-12.9% Hub+baseline time**

between the compared baselines.

The candidate was promoted only after correctness, deterministic release, update, rollback, Doctor/migration and immutability gates passed.

### Lesson

The optimization loop is:

> **measure → form a narrow hypothesis → change one mechanism → fault-test → gate on Windows → reject or promote**

## Engineering takeaway

The project moved from “automation that works on my machine” toward a system where a change has to answer four questions:

1. **What state can this change affect?**
2. **How can it fail, and how is that failure recovered?**
3. **How do we prove the tested bytes are the released bytes?**
4. **Can another run reproduce the same result without hidden local state?**

That process — more than any individual feature — is the core portfolio value of Keelaryn.
