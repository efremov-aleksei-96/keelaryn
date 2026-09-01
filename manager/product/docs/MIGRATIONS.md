# Instance identity and migrations

A Keelaryn Hub is identified by `_System/INSTANCE.json` (`keelaryn.instance.v1`). The UUID survives revision changes, system upgrades and folder moves.

`CHECK_MIGRATIONS.cmd` computes a path from the installed `system_version` to `product/release.json`. A complete path is not automatically executable: any non-`manager_safe` step produces `review_required`.

`APPLY_MIGRATIONS.cmd` only executes explicit `manager_safe` operations and refuses semantic merges.

Major namespace/history repair and customized governance convergence belong to Chat Manager. The 2.0.0 -> 2.1.0 transition is registered as `chat_manager_required`.

Moving a Hub does not require a system migration. Use `BIND_INSTANCE.cmd` if automatic identity-based reconciliation cannot resolve the location unambiguously.

## Legacy Core__ namespace compatibility

Pre-Keelaryn generic installations may use `Core__Manager`, `Core__Hub` and `corehub.*` schemas. These identifiers are compatibility/history aliases only. New Genesis and releases use Keelaryn names exclusively.

Historical schema/protocol identifiers are facts and must remain historical facts. Migration must never globally rewrite `corehub.artifact.v1/v2/v3` or `corehub.router.v1/v2` into fictitious Keelaryn predecessor schemas.

The namespace migration uses the same generic governance overlay as Genesis and preserves user-owned Areas/Projects/Records/Resources. Where customized governance or historical provenance requires semantic reconciliation, Chat Manager is required.

Local naming conventions such as arbitrary numeric prefixes are not part of the product's legacy namespace and are not encoded as compatibility aliases.
