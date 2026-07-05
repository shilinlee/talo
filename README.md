# Talo

Talo is agent-native remote development automation.

[中文文档](README.zh-CN.md)

It keeps the local machine as the source of truth while using a remote SSH host and Docker container as a
disposable execution backend:

```text
local project/worktree
  -> taloctl <env> sync
remote workspace mirror
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

`remote_base` is the remote base directory. Talo derives the project workspace as:

```text
$remote_base/.talo/workspaces/$project
```

`project` is the basename of the local git root, or the current working directory when outside git.

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

- **Linux/macOS:** `taloctl <env> sync` uses the packaged rsync script.
- **Native Windows:** `taloctl <env> sync` uses Paramiko SFTP and does not require rsync, bash, Git Bash, MSYS2, or WSL.
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

## Agent usage

Agent workflow guidance lives in `skills/talo-remote-dev/SKILL.md`; a Chinese reference is available at
`skills/talo-remote-dev/SKILL.zh-CN.md`.

## Safety model

- Local files are authoritative.
- Remote workspaces are disposable mirrors.
- `.git/`, `.talo/`, legacy `.envhub/`, virtualenvs, `node_modules/`, and Python caches are excluded from sync.
- Remote commands return real stdout/stderr and exit codes for local analysis.
