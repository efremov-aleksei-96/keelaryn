# Instance identity and migrations

A Keelaryn Hub is identified by `_System/INSTANCE.json` (`keelaryn.instance.v1`). The UUID survives revision changes, system upgrades and folder moves.

Maintenance > Check migrations (legacy alias `CHECK_MIGRATIONS.cmd`) computes a path from the installed `system_version` to `product/release.json`. A complete path is not automatically executable: any non-`manager_safe` step produces `review_required`.

Maintenance > Apply migrations (legacy alias `APPLY_MIGRATIONS.cmd`) only executes explicit `manager_safe` operations and refuses semantic merges.

Major namespace/history repair and customized governance convergence belong to Chat Manager. The 2.0.0 -> 2.1.0 transition is registered as `chat_manager_required`.

Moving a Hub does not require a system migration. Use Maintenance > Bind existing Hub (legacy alias `BIND_INSTANCE.cmd`) if automatic identity-based reconciliation cannot resolve the location unambiguously.

## System version versus governance revision

`system_version` and generic `governance_revision` are separate compatibility axes.

- `system_version` is structural and advances only through the migration registry.
- `_System/GOVERNANCE.json` records the generic-governance revision actually adopted by the Hub plus contract-specific revisions such as Workspace checkout.
- `product/release.json` declares the governance revision expected by the running Manager.
- Doctor reports governance compatibility independently of migration status.

A Hub may therefore be structurally current while Doctor reports that Chat Manager governance reconciliation is required. Manager update/install does not mutate the Hub to clear that warning.

## Legacy Core__ namespace compatibility

Pre-Keelaryn generic installations may use `Core__Manager`, `Core__Hub` and `corehub.*` schemas. These identifiers are compatibility/history aliases only. New Genesis and releases use Keelaryn names exclusively.

Historical schema/protocol identifiers are facts and must remain historical facts. Migration must never globally rewrite `corehub.artifact.v1/v2/v3` or `corehub.router.v1/v2` into fictitious Keelaryn predecessor schemas.

The namespace migration uses the same generic governance overlay as Genesis and preserves user-owned Areas/Projects/Records/Resources. Where customized governance or historical provenance requires semantic reconciliation, Chat Manager is required.

Local naming conventions such as arbitrary numeric prefixes are not part of the product's legacy namespace and are not encoded as compatibility aliases.

## Workspace governance convergence

Workspace checkout governance is instance-owned once a Hub exists and may have local customization. Manager updates therefore do not silently overwrite an existing Hub's `_System/WORKSPACE.md`, `_System/GOVERNANCE.json` or `Resources/Prompts/Workspace Checkout.md`.

The canonical generic governance overlay now owns the Workspace Checkout prompt as well as the `_System` governance documents. `_System/GOVERNANCE.json` declares the target `managed_paths`, `governance_revision`, `workspace_protocol` and `workspace_checkout_revision`.

When a newer Manager ships revised governance, an existing Hub adopts it through the normal Hub reconciliation path:

```text
CURRENT -> CANDIDATE -> Chat Manager -> APPROVED -> CURRENT
```

Reconciliation preserves unrelated user content/customization, incorporates the target governance semantics, writes the matching governance receipt only after the change is complete, advances the normal data revision, and rebuilds deterministic metadata. It never replaces the Hub with `product/starter/hub` and never advances `system_version` merely to clear governance drift.

For the current Workspace contract, entity-bound `keelaryn.workspace.v1` checkouts carry `source_entity_id`, `source_entity_title` and `suggested_chat_title`; legacy v1 checkouts without those optional informational fields remain readable.
