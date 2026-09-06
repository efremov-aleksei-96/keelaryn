# Troubleshooting

## `Keelaryn.cmd` does not start

Keelaryn targets Windows PowerShell 5.1. Start from the packaged Windows release and keep the extracted directory structure intact.

If Windows has blocked downloaded files, inspect the file Properties dialog and your Windows security notification rather than disabling system-wide security controls.

## I downloaded the GitHub source ZIP and Genesis refuses to create `hub`

Use the **GitHub Release Generic DISTRIBUTION** instead. The source repository intentionally contains a public `hub/README.md` boundary marker; it is source/test material, not a clean runtime installation layout.

## The menu opens but says the Hub is unavailable

For a new installation, create a Hub through:

```text
Advanced → Genesis new Hub
```

For an existing Hub, use the explicit binding action. Do not create or edit `manager\state\binding.json` manually.

## Doctor reports a failure

Doctor is intentionally fail-closed. Read the reported finding before changing files. Common categories include:

- stale or ambiguous Hub binding;
- missing/invalid CURRENT baseline;
- managed Manager source drift;
- package validation failure;
- migration requirement;
- unsafe filesystem collision/reparse point.

The detailed report is written under:

```text
manager\state\logs\DOCTOR_REPORT.json
```

## An update package is rejected

Do not unzip an UPDATE over the installed Manager. Use **Install update package...** or the explicit Manager update action. Rejection normally means the package failed schema, compatibility, path, hash or installed-state validation.

## A file is locked

Keelaryn performs bounded retries only for operations that explicitly allow them. On a terminal Windows sharing violation it may report the process/service that owns the lock through the Windows Restart Manager API. Keelaryn does not terminate that process automatically.

Close the application that owns the file and retry the operation.

## I moved the Keelaryn folder

Run **Doctor**. Canonical sibling Hub discovery may recover by stable instance identity, but ambiguous discovery is refused. Use explicit binding if required.

## I want a completely clean reinstall

Keep a backup of your existing `hub\` first. Extract the latest `Keelaryn_v<version>_Windows.zip` to a new location, then bind the new Manager to the existing Hub. Do not delete the old installation until Doctor passes against the intended Hub.

## I found a reproducible bug

When opening a GitHub issue, include the smallest reproducible case and exact error output. Do not attach a personal Hub, credentials or private logs unless you have deliberately sanitized them.
