---
name: talo-remote-dev
description: Use when a local project should be synced to a configured Talo remote execution backend, then built, tested, or inspected through taloctl while keeping local files as the source of truth.
version: 0.1.0
author: Talo contributors
license: MIT
metadata:
  hermes:
    tags: [talo, taloctl, remote-development, ssh, docker, rsync, local-ai]
    related_skills: [systematic-debugging, test-driven-development]
---

# Talo Remote Development

## Overview

Talo is an agent-native remote development controller. Use `taloctl` when the local machine should remain the
source of truth, while a remote SSH host and Docker container provide a disposable execution backend.

The core loop is:

```text
local project/worktree
  -> taloctl <env> sync
remote workspace mirror
  -> taloctl <env> docker "<test/build command>"
stdout/stderr
  -> local agent analysis
```

Do not treat the remote workspace as the real repository. It is a mirror that can be deleted and recreated.

## When to Use

Use this skill when:

- The user asks to run local project tests/builds on a configured remote machine.
- The task mentions Talo, `taloctl`, `.talo`, remote Docker execution, or rsyncing code to a backend.
- Local AI credentials, git state, and source edits should stay local, but heavy execution should happen remotely.
- You need to inspect remote containers, run a command in a project workspace, or verify accelerator visibility.

Do not use this skill for production deployment, bidirectional sync, or editing source files directly on the remote
workspace.

## Configuration Model

Runtime configuration lives outside the source tree:

```text
~/.talo/envs.yaml
~/.talo/scripts/        # optional user-overridden scripts
```

Public examples must use placeholders only:

```yaml
devbox:
  host: devbox.example
  remote_base: /home/devuser
  container: dev-container
  shell: bash
```

Important fields:

- `host`: SSH host or alias.
- `remote_base`: base directory on the remote host.
- `container`: Docker container used for project commands.
- `shell`: shell used inside the container, usually `bash`.

Talo derives the remote workspace from the local project name:

```text
$remote_base/.talo/workspaces/$project
```

`project` is the basename of the local git root, or the current directory when outside git.

## Command Surface

Use only this public command surface unless the user says their Talo version has changed:

```bash
taloctl list
taloctl <env> config
taloctl <env> sync
taloctl <env> docker "<command-in-project-workspace>"
taloctl <env> exec "<remote-host-command>"
taloctl <env> ps
taloctl <env> pull <remote-path> <local-path>
taloctl <env> push <local-path> <remote-path>
```

Prefer `sync` plus `docker` for normal build/test loops. Use `exec`, `pull`, and `push` only as escape hatches.

## Standard Workflow

### 1. Confirm the target environment and workspace

Run from the intended local repo or project directory:

```bash
taloctl list
taloctl <env> config
```

Completion criteria:

- The expected environment appears in `taloctl list`.
- `taloctl <env> config` shows the intended local root, project name, container, and remote workspace.

### 2. Sync local files to the remote mirror

After local edits, sync before remote execution:

```bash
taloctl <env> sync
```

Completion criteria:

- Command exits with code 0.
- Output indicates sync completed.
- The remote workspace path is under `$remote_base/.talo/workspaces/<project>`.

### 3. Run the requested command in the container

Use `docker` for project build/test commands:

```bash
taloctl <env> docker "python -m pytest"
taloctl <env> docker "npm test"
taloctl <env> docker "npu-smi info"
```

Completion criteria:

- The real command ran inside the configured container.
- stdout/stderr and the exit code are available locally for analysis.

### 4. Analyze locally, fix locally, repeat

If remote output shows a failure, edit local files, run `taloctl <env> sync`, then rerun the smallest relevant remote
command. Keep the remote workspace disposable.

## Safety Rules

1. Local files are authoritative.
2. Remote workspaces are mirrors, not source repositories.
3. Do not rely on remote `.git`; sync intentionally excludes git metadata.
4. Always sync after local edits and before remote tests.
5. Do not place real host aliases, usernames, home paths, container names, tokens, or credentials in public examples.
6. Avoid new commands until actual usage shows a clear need.

## Common Pitfalls

1. **Wrong current directory.** `project` is derived from the local git root or cwd. Check `taloctl <env> config` before
   syncing from an unfamiliar shell.
2. **Stale remote code.** If you edited locally but did not run `sync`, remote tests may use old files.
3. **Confusing `exec` and `docker`.** `exec` runs on the remote host; `docker` runs in the configured container.
4. **Treating remote files as durable.** The next sync can overwrite them.
5. **Leaking local names.** Public docs should use `devbox`, `devbox.example`, `/home/devuser`, and `dev-container`.

## Verification Checklist

Before reporting success:

- [ ] `taloctl <env> config` was checked when path correctness mattered.
- [ ] `taloctl <env> sync` ran after local changes.
- [ ] `taloctl <env> docker "..."` ran the actual requested command when container execution was needed.
- [ ] Results are based on real stdout/stderr and exit codes.
- [ ] Any public docs or examples use generic placeholders only.
