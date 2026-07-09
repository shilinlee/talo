---
name: talo-remote-dev-zh-cn
description: 当本地项目需要同步到已配置的 Talo 远端执行后端，并通过 taloctl 在远端构建、测试或检查，同时保持本地文件为唯一可信源时使用。
version: 0.1.0
author: Talo contributors
license: MIT
metadata:
  hermes:
    tags: [talo, taloctl, remote-development, ssh, docker, rsync, local-ai, chinese]
    related_skills: [talo-remote-dev]
---

# Talo 远端开发工作流

## 概览

Talo 是面向 AI agent 的远端开发控制器。当本地机器应该保持为源码可信源，而远端 SSH 主机和 Docker
容器只作为一次性执行后端时，使用 `taloctl`。

核心循环是：

```text
本地项目 / worktree
  -> taloctl <env> bootstrap   # git 分支首次搭建
远端 git workspace 镜像
  -> taloctl <env> sync        # 后续增量 overlay
  -> taloctl <env> docker "<测试或构建命令>"
stdout/stderr
  -> 本地 agent 分析
```

远端 workspace 仍然是可以删除、重建、覆盖的镜像。git 仓库场景下，`bootstrap` 会让远端自己 clone 当前分支，方便在远端使用 `git diff` / `git status` 检查 overlay 后的工作区状态。

## 什么时候使用

在以下情况使用这个 skill：

- 用户希望把本地项目的测试或构建放到已配置的远端机器上运行。
- 任务提到 Talo、`taloctl`、`.talo`、远端 Docker 执行，或把代码 rsync 到执行后端。
- AI 凭据、git 状态和源码编辑应该留在本地，但重型执行应该发生在远端。
- 需要查看远端容器、在项目 workspace 里执行命令，或验证加速卡 / NPU / GPU 可见性。

不要把它用于生产部署、双向同步，或直接在远端 workspace 修改源码。

## 配置模型

运行时配置放在源码树之外：

```text
~/.talo/envs.yaml
~/.talo/scripts/        # 可选的用户覆盖脚本
```

公开示例只能使用通用占位符：

```yaml
devbox:
  host: devbox.example
  remote_base: /home/devuser
  container: dev-container
  shell: bash
```

字段含义：

- `host`：SSH 主机名或别名。
- `remote_base`：远端主机上的基础目录。
- `container`：执行项目命令的 Docker 容器。
- `shell`：容器内使用的 shell，通常是 `bash`。

Talo 会从本地项目名推导远端 workspace。git 仓库使用当前分支隔离目录：

```text
$remote_base/workspace/worktress/$project/$branch
```

`project` 是本地 git 根目录的 basename，`branch` 是安全化后的当前分支名。如果当前目录不在 git 仓库里，则继续使用 legacy 路径：

```text
$remote_base/.talo/workspaces/$project
```

## SSH 前置条件

Talo 假设 SSH key-based 登录已经配置好。如果远端目前需要密码登录，先让用户把公钥安装到远端；不要在 Talo 中保存或处理密码。

用直接目标或 SSH config alias 验证：

```bash
ssh devuser@devbox.example 'echo talo-ssh-ok'
ssh devbox 'echo talo-ssh-ok'
```

## 命令表面

除非用户明确说明自己的 Talo 版本已经变化，否则只使用这些公开命令：

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
taloctl <env> docker "<项目 workspace 内执行的命令>"
taloctl <env> exec "<远端主机命令>"
taloctl <env> ps
taloctl <env> pull <remote-path> <local-path>
taloctl <env> push <local-path> <remote-path>
```

Agent 自动配置时优先使用 `taloctl env add` / `taloctl env update`，不要手写 YAML。`--host` 只接受主机名、IP 或 SSH alias；不要传 `user@host`。如果要写 SSH config，单独传 `--user`；只有私钥文件已经存在时才传 `--identity-file`。

常规构建 / 测试循环优先使用 `bootstrap`（首次）+ `sync`（后续）+ `docker`。`exec`、`pull`、`push` 只作为低层 escape hatch 使用。

## 平台说明

- Linux/macOS 使用 rsync 同步 backend。
- 原生 Windows 使用 Paramiko SFTP 同步，不要求本地安装 rsync、bash、Git Bash、MSYS2 或 WSL。
- 同步 backend 完全按平台自动选择，不要为它添加配置字段。
- 原生 Windows 仍需要 Python、Paramiko 和本地 OpenSSH `ssh` 可执行文件。Windows 安装 Talo 会通过平台依赖拉取 Paramiko；源码安装也可以用 `python -m pip install '.[windows]'`。
- `pull` 和 `push` 仍使用 legacy rsync 脚本；在迁移前，Windows 常规构建 / 测试循环不要依赖它们。

## 标准流程

### 1. 确认目标环境和 workspace

在目标本地仓库或项目目录下执行：

```bash
taloctl list
taloctl <env> config
```

完成标准：

- `taloctl list` 能看到预期环境。
- `taloctl <env> config` 显示预期的本地根目录、项目名、容器和远端 workspace。

### 2. 首次 bootstrap 远端分支 workspace

git 仓库第一次使用某个分支时，先执行：

```bash
taloctl <env> bootstrap
```

完成标准：

- 命令以 0 退出。
- 远端 workspace 位于 `$remote_base/workspace/worktress/<project>/<branch>` 之下。
- 远端 workspace 包含 `.git/`。
- 如果目标目录已经有任何数据，bootstrap 会报错退出，不会自动删除。

### 3. 同步本地文件到远端镜像

bootstrap 完成后，本地改动、远端执行前先同步：

```bash
taloctl <env> sync
```

完成标准：

- 命令以 0 退出。
- 输出表明同步完成。
- `sync` 只做简单校验和增量 overlay，不负责首次 clone。

### 4. 在容器中运行请求的命令

项目构建 / 测试命令使用 `docker`：

```bash
taloctl <env> docker "python -m pytest"
taloctl <env> docker "npm test"
taloctl <env> docker "npu-smi info"
```

完成标准：

- 真实命令在配置的容器中运行。
- stdout/stderr 和退出码能在本地用于分析。

### 5. 本地分析、本地修复、循环验证

如果远端输出显示失败，在本地修改文件，执行 `taloctl <env> sync`，然后重新运行最小相关远端命令。
远端 workspace 始终视为可丢弃。

## 安全规则

1. 本地文件是权威源。
2. 远端 workspace 是镜像，即使包含由 `bootstrap` 创建的 `.git/`，也不是权威源码。
3. 不要直接复制本地 `.git/`；远端 `.git/` 只能来自远端 clone。
4. 本地修改后、远端测试前必须同步。
5. 公开示例里不要放真实 host alias、用户名、home 路径、容器名、token 或凭据。
6. 只有真实使用显示出明确需求时，才新增命令。

## 常见坑

1. **当前目录错误。** `project` 从本地 git 根目录或 cwd 推导。不熟悉 shell 状态时，先看
   `taloctl <env> config`。
2. **远端代码过期。** 本地改了但没有 `sync`，远端测试可能跑旧文件。
3. **混淆 `exec` 和 `docker`。** `exec` 在远端主机运行；`docker` 在配置的容器内运行。
4. **把远端文件当成持久状态。** 下一次同步可能覆盖远端文件。
5. **泄露本地名称。** 公开文档使用 `devbox`、`devbox.example`、`/home/devuser`、`dev-container`。

## 验证清单

报告成功前确认：

- [ ] 路径正确性重要时，已经检查 `taloctl <env> config`。
- [ ] 本地修改后已经执行 `taloctl <env> sync`。
- [ ] 需要容器执行时，已经运行真实的 `taloctl <env> docker "..."` 命令。
- [ ] 结论基于真实 stdout/stderr 和退出码。
- [ ] 公开文档或示例只使用通用占位符。
