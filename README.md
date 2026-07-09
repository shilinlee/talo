# Talo

Talo is agent-native remote development automation.

[中文文档](README.zh-CN.md)

It keeps the local machine as the source of truth while using a remote SSH host and Docker container as a
disposable execution backend:

```text
local project/worktree
  -> taloctl <env> bootstrap   # first time for a git branch
remote git workspace
  -> taloctl <env> sync        # later incremental overlay
  -> taloctl <env> docker "<test/build command>"
stdout/stderr
  -> local AI/agent analysis
```

The goal is to remove repeated environment setup pain for AI agents and developers: configure a remote backend
once, then let agents sync, run, verify, and inspect results through one stable command surface.

## Install from source

From this repository:

```bash
python3 -m pip install -e .
```

If your Python installation is externally managed, prefer a venv, `pipx`, or `uv tool install`.

Native Windows installs pull in `paramiko` for incremental SFTP sync. On Linux and macOS, Talo keeps using the
rsync backend by default.

## Install from TestPyPI

For public testing, install the current test release from TestPyPI:

```bash
python3 -m pip install --index-url https://test.pypi.org/simple/ --no-deps talo==0.1.0
```

## Runtime layout

User configuration lives outside the source tree:

```text
~/.talo/
  envs.yaml
```

## Config

Create `~/.talo/envs.yaml`:

```yaml
devbox:
  host: devbox.example
  remote_base: /home/devuser
  container: dev-container
  shell: bash
```

`remote_base` is the remote base directory. For git repositories, Talo derives the branch workspace as:

```text
$remote_base/workspace/worktress/$project/$branch
```

`project` is the basename of the local git root. `branch` is the current git branch with path-unsafe characters replaced.
For directories outside git, Talo keeps the legacy workspace layout:

```text
$remote_base/.talo/workspaces/$project
```

## SSH prerequisite

Talo expects SSH key-based login to work before it runs remote commands. If your remote host only accepts a password,
install your public key into the remote user's `~/.ssh/authorized_keys` first. Then verify non-interactive access:

```bash
ssh devuser@devbox.example 'echo talo-ssh-ok'
```

If you use an SSH config alias, verify the alias instead:

```bash
ssh devbox 'echo talo-ssh-ok'
```

## Platform notes

- **Linux/macOS:** `taloctl <env> sync` uses the packaged rsync script for the overlay step.
- **Native Windows:** `taloctl <env> sync` uses Paramiko SFTP for the overlay step and does not require rsync, bash, Git Bash, MSYS2, or WSL.
- Sync backend selection is automatic by platform; no config field is needed.
- `pull` and `push` still use the legacy rsync scripts and are escape hatches, not the normal build/test loop.

## Commands

```bash
taloctl list
taloctl version
taloctl env list
taloctl env show <name>
taloctl env add <name> --host <host-or-ip-or-alias> --remote-base <path> [--container <name>] [--yes]
taloctl env update <name> [--host <host-or-ip-or-alias>] [--remote-base <path>] [--container <name>] [--yes]
taloctl <env> config
taloctl <env> bootstrap
taloctl <env> sync
taloctl <env> docker "<command-in-project-workspace>"
taloctl <env> exec "<remote-host-command>"
taloctl <env> ps
taloctl <env> pull <remote-path> <local-path>
taloctl <env> push <local-path> <remote-path>
```

`env add` and `env update` are agent-friendly configuration commands. `--host` accepts only a host name, IP address, or
SSH alias; do not pass `user@host`. Use `--user` only when also writing SSH config:

```bash
taloctl env add devbox \
  --host devbox.example \
  --user devuser \
  --remote-base /home/devuser \
  --container dev-container \
  --ssh-config \
  --identity-file ~/.ssh/id_ed25519 \
  --yes
```

When `--identity-file` is provided, the private key file must already exist. Talo will not generate keys or copy public
keys to the server.

## Git branch bootstrap

For git repositories, run `bootstrap` once before the first `sync` for a branch:

```bash
taloctl devbox bootstrap
```

`bootstrap` requires the remote host to be able to clone the local `origin` URL. It only works when the target remote
workspace does not exist or is empty; if that directory already contains data, Talo exits instead of deleting it.
After the clone succeeds, Talo runs one overlay sync so local uncommitted changes appear as remote working-tree diffs.
Later `sync` calls only check that the remote workspace exists, contains `.git/`, and is on the same branch, then run the
overlay sync.

Agent workflow guidance lives in `skills/talo-remote-dev/SKILL.md`.

## Safety model

- Local files are authoritative.
- Remote workspaces are disposable mirrors, even when they contain a git clone.
- Local `.git/` is never copied directly. Git workspaces are created remotely by `bootstrap`.
- `.git/`, `.talo/`, legacy `.envhub/`, virtualenvs, `node_modules/`, and Python caches are protected from overlay sync.
- Remote commands return real stdout/stderr and exit codes for local analysis.
