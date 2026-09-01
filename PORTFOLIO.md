# Keelaryn as a portfolio project

Keelaryn is useful as evidence of engineering ability because it is not a one-screen demo: it has state identity, update contracts, migration, rollback, release packaging, fault injection, performance measurement, and explicit negative knowledge from rejected candidates.

## Roles this project supports

The strongest fit is for entry-level or junior roles involving:

- Technical Support / L2 Support
- IT Operations / Windows Operations
- QA with a technical or automation focus
- PowerShell / Windows automation
- Junior system administration
- Junior DevOps as a supporting project alongside Git/Linux/CI/CD/container skills
- Security-minded operations or application support

## Concrete skills visible in the repository

| Area | Evidence |
|---|---|
| Windows / PowerShell | PowerShell 5.1 runtime, CLI launchers, filesystem and process integration |
| Troubleshooting | Doctor reports, lock-owner diagnostics, explicit error paths |
| QA / testing | SelfTest, disposable release gates, fault injection, regression thresholds |
| Release engineering | deterministic builds, manifests, update bundles, retention, hash validation |
| Security | path/reparse/ZIP checks, fail-closed validation, no secret-bearing generic releases |
| Performance | profilers, benchmark gates, measured rejection/acceptance criteria |
| Architecture | product/instance separation, identity layers, lifecycle isolation |
| AI-assisted engineering | generated lossless AI_CONTEXT routes tied to the exact runtime hash |

## Interview-ready engineering stories

### 1. Optimize only after measuring

A Doctor hotspot was traced to SHA-256 digest-to-hex formatting. A microbenchmark showed that the PowerShell `ForEach-Object { ToString('x2') }` formatter dominated the cost for hundreds of hashes. Replacing only that representation step with .NET `BitConverter` preserved every digest while reducing the measured Doctor runtime by 7.8% overall and the portable-analysis phase by 32.3%.

Key point to explain: **the hash algorithm and input bytes did not change**; only conversion of the already-computed 32 digest bytes to hex changed.

### 2. Reject an optimization even when it is correct

Several candidates passed correctness checks but were not promoted because full-system benchmarks regressed. A metadata-snapshot experiment improved one subphase but increased total Doctor time; batched JSON and alternative property-access experiments were likewise rejected when the end-to-end result did not meet the acceptance threshold.

Key point: optimization was treated as an empirical release requirement, not as a code-style preference.

### 3. Fail safely during updates

Manager updates validate package metadata and hashes, snapshot the managed product, reject unsafe directory/reparse collisions before mutation, apply only the declared managed set, and validate the installed result. Disposable gates exercise failure modes and verify that Hub state remains unchanged.

### 4. Diagnose Windows file locks without killing processes

On terminal sharing violations the Manager can query the Windows Restart Manager API and report the process/service owner (PID, application type, restartability). It deliberately never invokes Restart Manager shutdown/restart operations.

### 5. Separate product source from user data

Generic release builders operate only on a managed allowlist and are Hub-blind. Personal instance state, CURRENT/CANDIDATE packages, logs, binding and local history are runtime artifacts and are excluded from public/source releases.

## How to describe the project concisely

> Built a Windows-oriented PowerShell management and release system with deterministic packaging, SHA-256 integrity validation, staged update/rollback, migration support, read-only diagnostics, fault-injection gates, Windows lock-owner diagnostics, and a generated task-routed AI development context. Used profiling and release thresholds to reject regressions and reduced end-to-end diagnostic runtime by about 8% in a production optimization.

## What not to claim

- Do not present Keelaryn as commercial production experience.
- Do not claim that every component was authored without AI assistance.
- Do not claim middle/senior engineering level from the project alone.
- Do not publish or demonstrate a personal Hub. Use Genesis or sanitized disposable instances.

The strongest framing is: **substantial independent engineering project demonstrating the ability to reason about correctness, safety, testing, Windows automation and release discipline despite limited commercial IT experience.**
