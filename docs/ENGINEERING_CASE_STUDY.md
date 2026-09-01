# Engineering case study: measurement-driven Manager development

## Objective

The development priorities are ordered deliberately:

1. correctness;
2. zero regression of existing capabilities;
3. data safety and rollback;
4. deterministic behavior;
5. security;
6. performance;
7. reduced AI context requirements;
8. maintainability.

Performance work is accepted only after correctness gates and end-to-end measurement.

## Example: SHA-256 rendering optimization

### Observation

Doctor spent substantial time in portable filesystem and CURRENT ZIP hashing. Profiling separated SHA-256 computation from conversion of the resulting 32 digest bytes to lowercase hexadecimal.

### Microbenchmark

On a real Hub/CURRENT workload with 178 files/entries:

| Workload | PowerShell pipeline | .NET BitConverter | Change |
|---|---:|---:|---:|
| Filesystem hashing | 43.747 ms | 15.178 ms | **-65.31%** |
| CURRENT entry hashing | 37.407 ms | 13.535 ms | **-63.82%** |

Pure hex formatting over repeated real digest values improved by about 93%.

### Change

Only the digest representation step changed:

- SHA-256 implementation stayed the same;
- stream/text/byte inputs stayed the same;
- lowercase 64-character output stayed byte-for-byte equivalent.

The old formatter was retained inside SelfTest as an equivalence oracle.

### Release-gate result

A 13-sample Windows PowerShell 5.1 gate on the same disposable Hub/CURRENT baseline measured:

| Metric | 4.4.25 | 4.4.30 | Change |
|---|---:|---:|---:|
| Hub + baseline | 578.5 ms | 503.8 ms | **-12.9%** |
| Total Doctor | 828.8 ms | 764.3 ms | **-7.8%** |
| Portable analysis | 153.9 ms | 104.2 ms | **-32.3%** |
| CURRENT baseline | 206.4 ms | 182.2 ms | **-11.7%** |

The candidate was promoted only after parser, SelfTest, deterministic release, disposable native update, Doctor, migration, rollback and production-immutability gates passed.

## Negative results are part of the process

Not every optimization was shipped.

Examples of rejected approaches included:

- capturing extra metadata text during the portable hash pass: correctness passed, but total Doctor time regressed;
- batching JSON parsing: the intended phase became slower;
- alternative PSObject property-access paths: microbenchmark results did not translate into reliable full-Doctor improvements and some candidates exposed PowerShell semantic edge cases.

Issued defective or regressing candidates were not silently rewritten. A new candidate number was required after defects were found.

## Reliability work beyond performance

The same development process produced:

- per-operation Hub ZIP inspection sessions to remove duplicate archive passes;
- target/path safety checks for Manager updates;
- Windows Restart Manager lock-owner diagnostics;
- deterministic release retention with legacy-bundle compatibility kept narrow;
- canonical `tests/work` and `tests/results` lifecycle;
- candidate transport fallback for attachment/transport resilience;
- AI_CONTEXT slicing fixes for Windows PowerShell 5.1 UTF-8/parser offset behavior.

## Engineering takeaway

The important result is not any single percentage. The project demonstrates a loop of:

**measure → form a narrow hypothesis → fault-test → gate on Windows → reject or promote → rebuild from verified production**.
