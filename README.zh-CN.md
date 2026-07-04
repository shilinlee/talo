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

## 命令

```bash
taloctl list
taloctl <env> config
taloctl <env> sync
taloctl <env> docker "<项目 workspace 内执行的命令>"
taloctl <env> exec "<远端主机命令>"
taloctl <env> ps
taloctl <env> pull <remote-path> <local-path>
taloctl <env> push <local-path> <remote-path>
```

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
