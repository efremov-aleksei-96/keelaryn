# Keelaryn migrations

The registry in `index.json` is the only source of declared system-version transitions.

`apply_mode` meanings:

- `manager_safe` — transactional Local Manager execution is permitted, but only for constrained platform-owned operations whose expected base hashes match exactly.
- `chat_manager_required` — a path exists, but semantic/full reconciliation is required; Maintenance > Check migrations (legacy alias `CHECK_MIGRATIONS.cmd`) reports `review_required` and Maintenance > Apply migrations (legacy alias `APPLY_MIGRATIONS.cmd`) must not apply it automatically.

System 2.0.0 -> 2.1.0 is intentionally `chat_manager_required` because it reconciles customized governance and repairs namespace provenance while converging on the 2.1 portable-manifest contract.
