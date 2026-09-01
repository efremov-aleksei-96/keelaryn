# Genesis and onboarding

`GENESIS_KEELARYN__HUB.cmd` creates the canonical sibling `hub` next to `manager` in a 4.4+ layout and canonical `r0001`. There is no fabricated `r0000`.

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

Before committing r0001, Manager independently validates metadata, source manifest and payload identity. Local `.obsidian`/Git/workstation state is never included in the portable checkpoint.

Initial Area/Project names are planned before r0001 is committed. Manager rejects filename collisions after sanitization, collisions with canonical template files, Windows reserved device names, wikilink-breaking bracket names after normalization, and generated slugs longer than 80 characters. The display title remains the user-provided name; only the filesystem slug is normalized.
