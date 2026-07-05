# Talo

Talo 是面向 AI agent 的远端开发自动化工具。

[English README](README.md)

它让本地机器保持为源码可信源，同时把远端 SSH 主机和 Docker 容器作为可丢弃的执行后端：

```text
本地项目 / worktree
  -> taloctl <env> sync
远端 workspace 镜像
  -> taloctl <env> docker "<测试或构建命令>"
stdout/stderr
  -> 本地 AI / agent 分析
```

目标是减少 AI agent 和开发者反复配置环境的成本：只需配置一次远端后端，之后 agent 就可以通过一个稳定的命令表面完成同步、运行、验证和检查。

## 从源码安装

在本仓库根目录执行：

```bash
python3 -m pip install -e .
```

如果你的 Python 是 externally managed，优先使用 venv、`pipx` 或 `uv tool install`。

原生 Windows 安装会拉取 `paramiko`，用于增量 SFTP 同步。Linux 和 macOS 默认继续使用 rsync backend。

## 从 TestPyPI 安装

公测版本可以从 TestPyPI 安装：

```bash
python3 -m pip install --index-url https://test.pypi.org/simple/ --no-deps talo==0.1.0
```

## 运行时目录

用户配置放在源码树之外：

```text
~/.talo/
  envs.yaml
  scripts/          # 可选的用户覆盖脚本
```

当 `~/.talo/scripts/<name>.sh` 不存在时，Talo 会使用包内置脚本作为 fallback。

## 配置

创建 `~/.talo/envs.yaml`：

```yaml
devbox:
  host: devbox.example
  remote_base: /home/devuser
  container: dev-container
  shell: bash
```

`remote_base` 是远端基础目录。Talo 会推导项目 workspace：

```text
$remote_base/.talo/workspaces/$project
```

`project` 是本地 git 根目录的 basename；如果当前目录不在 git 仓库内，则使用当前目录名。

## SSH 前置条件

Talo 默认要求远端 SSH 免密登录已经可用，然后再执行远端命令。如果远端目前只能用密码登录，请先把本地公钥安装到远端用户的 `~/.ssh/authorized_keys`。

Linux/macOS 且有 `ssh-copy-id` 时：

```bash
ssh-copy-id -i ~/.ssh/id_ed25519.pub devuser@devbox.example
```

通用 OpenSSH fallback：

```bash
cat ~/.ssh/id_ed25519.pub | ssh devuser@devbox.example 'mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'
```

Windows PowerShell：

```powershell
Get-Content $env:USERPROFILE\.ssh\id_ed25519.pub | ssh devuser@devbox.example "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

然后验证 SSH 是否可用：

```bash
ssh devuser@devbox.example 'echo talo-ssh-ok'
```

如果使用 SSH config alias，则验证 alias：

```bash
ssh devbox 'echo talo-ssh-ok'
```

## 平台说明

- **Linux/macOS：** `taloctl <env> sync` 使用包内置 rsync 脚本。
- **原生 Windows：** `taloctl <env> sync` 使用 Paramiko SFTP 做增量文件更新，不要求 rsync、bash、Git Bash、MSYS2 或 WSL。
- 同步 backend 完全按平台自动选择，不需要配置字段。
- `exec`、`docker` 和 `ps` 会直接调用本地 `ssh` 可执行文件，不要求本地 bash。
- `pull` 和 `push` 仍使用 legacy rsync 脚本，只作为低层 escape hatch，不是常规构建 / 测试循环。

## 命令

```bash
taloctl list
taloctl version
taloctl env list
taloctl env show <name>
taloctl env add <name> --host <host-or-ip-or-alias> --remote-base <path> [--container <name>] [--yes]
taloctl env update <name> [--host <host-or-ip-or-alias>] [--remote-base <path>] [--container <name>] [--yes]
taloctl <env> config
taloctl <env> sync
taloctl <env> docker "<项目 workspace 内执行的命令>"
taloctl <env> exec "<远端主机命令>"
taloctl <env> ps
taloctl <env> pull <remote-path> <local-path>
taloctl <env> push <local-path> <remote-path>
```

`env add` 和 `env update` 是面向 agent 的配置命令。`--host` 只接受主机名、IP 或 SSH alias；不要传 `user@host`。只有在同时写 SSH config 时才使用 `--user`：

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

如果提供了 `--identity-file`，对应私钥文件必须已经存在。Talo 不会生成密钥，也不会把公钥复制到服务器。

## Agent 使用方式

Talo 仓库提供了 Hermes skill，用来教 agent 安全地使用远端开发循环：本地文件是权威源，远端 workspace 是可丢弃镜像，远端执行通过 `taloctl` 完成。

安装英文 skill：

```bash
hermes skills install https://raw.githubusercontent.com/shilinlee/talo/main/skills/talo-remote-dev/SKILL.md
```

仓库里也提供了中文参考译本：

```text
skills/talo-remote-dev/SKILL.zh-CN.md
```

然后在 Hermes 会话中加载：

```text
/skill talo-remote-dev
```

## 安全模型

- 本地文件是权威源。
- 远端 workspace 是可丢弃镜像。
- 同步会排除 `.git/`、`.talo/`、legacy `.envhub/`、虚拟环境、`node_modules/` 和 Python 缓存。
- 远端命令返回真实 stdout/stderr 和退出码，供本地分析。
