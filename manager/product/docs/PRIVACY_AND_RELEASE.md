# Privacy and clean release construction

Generic Keelaryn distributions are built exclusively from the Manager's managed product allowlist. Canonical Hub CURRENT files, inbox/history/logs/releases, local bindings and any user instance tree are outside that allowlist.

Development > Build generic distribution (legacy alias `BUILD_GENERIC_DISTRIBUTION.cmd`) produces a clean generic distribution. Development > Build full release (legacy alias `BUILD_RELEASE.cmd`) additionally produces source, update and release-manifest artifacts from the same allowlist.

Managed source is text-only and clean-room audited for user-like emails, phone-like values and absolute user-profile paths. Technical GUIDs and full SHA-256 digests are normalized before phone-pattern inspection so machine identities cannot trigger bare-number phone detection.

Portable Hub transport excludes workstation-local `.obsidian/**`, `.git/**`, `desktop.ini`, `Thumbs.db` and `.DS_Store`.

SOURCE may contain generated `Development/AI_CONTEXT/**`, derived exclusively from managed product source. It does not read Hub instance content, logs, history, inbox or local bindings. Installable DISTRIBUTION/UPDATE packages are rebuilt from the managed allowlist and exclude Development entirely.

## Hub candidate transport privacy

`Keelaryn__Hub_CANDIDATE_TRANSPORT_*.json` is instance-specific transport data, not a generic Manager release artifact. It can contain Base64-encoded exact bytes from changed Hub files and therefore must be protected, shared and retained with the same confidentiality expectations as the corresponding Hub CANDIDATE ZIP. Manager release/distribution builders must never absorb candidate transport JSON into generic SOURCE/DISTRIBUTION/UPDATE/AI_CONTEXT artifacts.

