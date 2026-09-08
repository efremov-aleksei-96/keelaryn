# Getting Started with Keelaryn

This guide takes a new Windows user from the GitHub page to a working local Hub without requiring Git or release-engineering knowledge.

## 1. Download the packaged release

Open the repository **Releases** page and download:

```text
Keelaryn_v<version>_Windows.zip
```

Do not use the repository source ZIP as your normal installation. The source tree contains development/test boundary directories that are intentionally absent from the Generic DISTRIBUTION.

## 2. Extract it

Extract the archive to a normal writable folder you control, for example:

```text
Documents\Keelaryn
```

Inside it you should see:

```text
keelaryn\
├── Keelaryn.cmd
└── manager\
```

Keelaryn is designed as a portable folder. Keep the whole `keelaryn` directory together.

## 3. Start Manager

Double-click:

```text
Keelaryn.cmd
```

The Manager opens in a console window. Normal operation does not require you to type PowerShell commands.

## 4. Complete first-run setup

On a clean installation from a current packaged release, startup shows:

```text
Welcome to Keelaryn

[1] Create a new Hub
[2] Connect an existing Hub
[3] Main menu for now
[0] Exit
```

### Create a new Hub

Choose **Create a new Hub**. Genesis asks for a small set of bounded initial choices:

- canonical language;
- purpose: personal / professional / mixed;
- timezone;
- optional Areas;
- optional live Projects.

You do not need to design the whole system immediately. A small initial Hub is preferable; it can evolve later.

After confirmation, Genesis creates `hub\` next to `manager\`, assigns a stable instance identity, builds derived metadata, creates the initial portable checkpoint and validates the result before committing it.

### Connect an existing Hub

Choose **Connect an existing Hub** and select the existing Hub directory. Manager validates the binding rather than treating that directory as a new Hub.

### Recovery behavior

If Manager sees a canonical `hub\` path, existing CURRENT baseline, explicit binding or Hub environment override but cannot resolve a healthy Hub, it does **not** assume a fresh installation. It shows recovery guidance instead of overwriting anything.

This is also why cloning the public source repository is not the normal installation path: the repository intentionally contains a boundary-only `hub/README.md`.

## 5. Run Doctor

After creating or connecting the Hub, run:

```text
Doctor
```

A healthy installation should complete without integrity failures. Doctor is the authoritative diagnostic path; the compact menu status is only a quick status display.

## 6. Open your Hub

Select:

```text
Open Hub
```

Your personal information lives under:

```text
keelaryn\hub\
```

Manager runtime state lives separately under:

```text
keelaryn\manager\state\
```

Do not put personal Hub data into the public source repository.

## 7. Optional: use it with ChatGPT

Keelaryn does not upload your Hub automatically. You decide what checkpoint or handoff to attach to ChatGPT.

Read **[Using Keelaryn with ChatGPT](docs/USING_WITH_CHATGPT.md)**. That guide separates ordinary project work from the stricter Chat Manager reconciliation workflow.

## 8. Updates

GitHub Releases normally contain two relevant assets:

- `Keelaryn_v<version>_Windows.zip` — complete clean installation / fresh start;
- `Keelaryn__Manager_Update_v<version>_Built.zip` — Manager update package for an existing installation.

For an existing installation, prefer the Manager UI:

```text
Install update package...
```

Manager copies the selected package into its inbox, verifies the copied bytes, validates the package contract and performs the transactional update path. Do not manually overwrite an installed `manager` directory with files from a newer release.

## 9. Moving or backing up Keelaryn

The important user-owned data is your `hub\` directory. Keep backups of the whole `keelaryn\` directory when practical so that Manager state and portable baseline history travel with it.

After moving the installation, run **Doctor**. If an explicit binding points to an old path, use the Manager binding action rather than editing binding JSON by hand.

## 10. If something does not work

See **[Troubleshooting](docs/TROUBLESHOOTING.md)**. When reporting a problem, include:

- Manager version;
- exact error text;
- whether the problem happened during startup, Genesis, Doctor or update;
- `manager\state\logs\manager.log` only after checking that you are comfortable sharing its contents.
