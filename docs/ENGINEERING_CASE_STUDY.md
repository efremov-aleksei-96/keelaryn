# Engineering case study: measurement-driven Manager development

## Objective

Development priorities are ordered: correctness; regression prevention; data safety/rollback; deterministic behavior; security; performance; reduced AI context; maintainability. Performance work is accepted only after correctness gates and end-to-end measurement.

## Example: SHA-256 rendering optimization

Profiling separated SHA-256 computation from conversion of the resulting digest bytes to lowercase hexadecimal. On a real Hub/CURRENT workload, replacing only the PowerShell formatting pipeline with .NET `BitConverter` preserved digest inputs/algorithm/output while substantially reducing formatting overhead. A Windows PowerShell 5.1 release gate measured approximately **-7.8% total Doctor time**, **-32.3% portable-analysis time**, and **-12.9% Hub+baseline time** between the compared baselines.

The candidate was promoted only after parser, SelfTest, deterministic release, disposable native update, Doctor, migration, rollback and production-immutability gates passed.

## Negative results are part of the process

Several technically correct experiments were rejected when end-to-end performance regressed or PowerShell semantics made them unsafe. Issued defective candidates were never silently replaced; a new candidate number was required.

## Later release-engineering lessons

Subsequent work exposed nondeterministic UPDATE bytes only when two release builds were moved to isolated roots. The failure was traced to a transition bootstrap that interpolated a build-root path during packaging. The gate itself was then separated into a reusable framework and qualified independently before further Manager candidates.

The current process uses a frozen Windows-qualified Gate Framework, isolated deterministic build roots, explicit SourceGate→FullGate evidence, tested-artifact handoff, rollback fault injection, and production immutability checks.

## Engineering takeaway

**measure → form a narrow hypothesis → fault-test → gate on Windows → reject or promote → rebuild from verified production.**
