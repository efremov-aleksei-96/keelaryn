# AI-assisted Manager development

Development > Build AI_CONTEXT (legacy alias `BUILD_AI_CONTEXT.cmd`) creates a deterministic, runtime-SHA-bound development context without reading the bound Hub. The generator is presentation-invariant: canonical managed source may be Hidden in an installed Windows Manager and is still read with hidden-safe metadata access. The context contains all managed product files except the monolithic runtime under `managed/`; the runtime itself is losslessly split into preamble, exact top-level function slices, inter-function global gaps and dispatch.

Use `TASK_ROUTER.json` first. Open the matching `routes/<task>.md`, which is now a compact index without duplicated source code, then only the listed function slices and managed files. `MANAGED_FILE_MAP.json` records exact source hashes and context paths, and `CONTEXT_MANIFEST.json` records hashes of every generated context file.

Generated slices are derived views. Patch canonical managed source, regenerate context, and validate the UPDATE through the installed Manager plus disposable Windows gate before production installation.

## Context-noise policy

Route files must reference exact slices rather than embedding duplicate function bodies. This keeps search results unique, reduces archive/index size, and avoids making the model reconcile multiple derived copies of the same canonical code.

The generator parses the already UTF-8-decoded runtime text with `Parser.ParseInput` and rejects any AST extent/text mismatch before emitting slices. This prevents Windows PowerShell 5.1 file-decoding differences from shifting function boundaries when non-ASCII source characters are present.

Generated Markdown is assembled as explicit line records and written with deterministic LF endings. The generator validates line-feed count and UTF-8 round-trip before accepting each route or `START_HERE.md`; this prevents PowerShell expression coercion from silently collapsing structural line breaks.

For Windows PowerShell 5.1 compatibility, managed executable `.ps1` source is restricted to ASCII bytes. Unicode values that matter to behavior are constructed by code point (for example `[char]0x00B9`) rather than embedded as source literals; this avoids UTF-8-without-BOM/ANSI decoding ambiguity.

The `lock_diagnostics` task route isolates Windows sharing-violation classification, lazy Restart Manager interop, owner formatting, atomic publication, log retry and terminal lock-error propagation so lock work does not require loading unrelated update/Doctor runtime.

The `genesis` route isolates Genesis planning/template construction and its starter/governance inputs. The `migrations` route covers registered system migrations, instance identity adoption, legacy namespace compatibility, canonical layout migration and finalization through the consolidated `MIGRATIONS.md` + `LAYOUT.md` documentation.

## Test-workspace context

The `tests_workspace` AI_CONTEXT route isolates the canonical `tests/work` + `tests/results` lifecycle and the Development > Prepare tests workspace (legacy alias `PREPARE_TESTS.cmd`) command so test-layout work does not require unrelated update/Doctor runtime.

## Candidate transport route

Use AI_CONTEXT route `candidate_transport` for fallback CANDIDATE transport work. It should include the builder/restorer, delta/path validators, Hub ZIP inspection helpers and `product/docs/CANDIDATE_TRANSPORT.md` without loading unrelated Doctor/update runtime.

## File hashing in the context builder

The AI_CONTEXT generator hashes source/context files with direct `.NET SHA256(Stream)` plus `BitConverter` lowercase hex formatting rather than repeated `Get-FileHash` cmdlet invocations. The algorithm and hashed bytes are unchanged; the optimization removes PowerShell cmdlet overhead from the hundreds of file hashes performed during a context build.

Task routes include `user_interface` and `repository_model` so UX/repository work does not require broad runtime loading.

## 4.8.7 AI_CONTEXT and physical runtime

Manager 4.8.7 keeps the validated 4.6.4 AI_CONTEXT hot-path optimization. The canonical function-map runtime is `product/runtime/Keelaryn__Manager.ps1`; `product/install/INSTALLATION.json` is the canonical managed-file map. Transition root bootstrap/version/manifest files exist only inside the 4.7.2-compatible UPDATE envelope and are not part of AI_CONTEXT managed source. Final hashing and lossless reconstruction remain fresh.

The Windows performance gate retains the robust in-process ABBA methodology introduced during the 4.6.4 release cycle and the +5% regression ceiling.