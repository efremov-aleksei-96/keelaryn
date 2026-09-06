# Tests

Reusable test infrastructure belongs here.

- `framework/manager-gate/` — frozen Windows-qualified Manager Gate Framework source.
- `work/` — disposable local candidate/install/fixture workspace; ignored except its README.
- `results/` — durable local gate evidence; ignored except its README.

The complete production-approval Full Gate remains a local Windows workflow because it uses a CURRENT-backed disposable Hub and verifies production immutability. GitHub Actions runs the Hub-blind SourceGate layer only.
