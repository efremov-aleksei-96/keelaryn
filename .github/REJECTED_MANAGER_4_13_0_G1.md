# Manager 4.13.0 g1 rejection

Date: 2026-09-06
Status: REJECTED

The exact `manager-4.13.0.zip` g1 archive reached the consolidated Windows Full Gate and failed during SourceGate root bootstrap SelfTest.

Failure chain:

- `Manager -SelfTest`
- qualification evidence compaction contract
- product SelfTest unconditionally attempted `New-Item -ItemType SymbolicLink` for the positive file-reparse regression fixture
- ordinary Windows installations may not have Developer Mode / `SeCreateSymbolicLinkPrivilege`, while the GitHub Windows runner did

Production Manager and production Hub were not modified.

4.13.0 product bytes are frozen as rejected and must not be silently changed. The corrective product candidate is 4.13.1.
