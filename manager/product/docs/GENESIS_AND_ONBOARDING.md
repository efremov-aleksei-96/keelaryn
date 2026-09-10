# Genesis and onboarding

On a clean canonical installation the first-run frontend offers **Create a new Hub** before the main menu. The same operation remains available as Advanced > Genesis new Hub (legacy alias `GENESIS_KEELARYN__HUB.cmd`). Genesis creates the canonical sibling `hub` next to `manager` in a 4.4+ layout. The initial Hub has internal monotonic `data_revision: 1` (legacy sequence `r0001`) and an immutable UTC `revision_time_utc`; human-facing UI uses the timestamp rather than `r0001`. There is no fabricated revision zero.

Genesis combines two product-owned sources:

1. `product/starter/hub` — minimal Areas/Projects/Records/Resources skeleton and Genesis record;
2. `product/governance/hub` — the same canonical governance overlay used by platform migrations.

System 2.1.0 Genesis always creates:

- `keelaryn.instance.v1`;
- `keelaryn.artifact.v3`;
- `keelaryn.index.v1`;
- `keelaryn.router.v2`;
- `keelaryn.manifest.v1`;
- `keelaryn.validation.v2`.

Before committing the initial revision, Manager independently validates metadata, source manifest and payload identity. Local `.obsidian`/Git/workstation state is never included in the portable checkpoint.

Initial Area/Project names are planned before the initial revision is committed. Manager rejects filename collisions after sanitization, collisions with canonical template files, Windows reserved device names, wikilink-breaking bracket names after normalization, and generated slugs longer than 80 characters. The display title remains the user-provided name; only the filesystem slug is normalized.


The interactive Manager frontend owns Genesis input and the commit confirmation. It serializes the validated choices into a short-lived `keelaryn.genesis-input.v1` document and invokes the runtime child non-interactively with explicit confirmation. Direct frontend automation must provide `-Path <config.json> -ConfirmChanges`; without explicit confirmation it is a safe no-op. The legacy compatibility command/runtime `-Genesis` path remains interactive for compatibility when invoked outside the Manager frontend.

## First-run safety

The frontend classifies startup before offering automatic onboarding. A fresh setup requires canonical layout, no valid Hub, no existing canonical `hub` path, no CURRENT baseline, no binding file and no Hub environment override. Any pre-existing state routes to recovery instead of Genesis. This preserves fail-closed behavior for moved/broken installations and for repository source checkouts whose public `hub/README.md` is a boundary marker rather than a user Hub.

After interactive Genesis or a successful first-run bind, the frontend runs Doctor immediately. Doctor remains authoritative; setup is reported ready only when that diagnostic path returns success.

<!-- multi-hub-genesis-v1 -->
## Additional Hub Genesis

After multi-Hub is initialized, additional Genesis Hubs use a direct child of the canonical `hubs` directory, for example `hubs/vova`.

The operation stages both the Hub and its instance-owned state, validates the generated `instance_id`, ARTIFACT and CURRENT, publishes the two trees, and commits the registry last. The previously active Hub remains active until an explicit switch.
