from __future__ import annotations

import os
import shlex
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Dict, List, Mapping, Optional

TALO_HOME_ENV = "TALO_HOME"
DEFAULT_TALO_HOME = Path.home() / ".talo"
NONE_VALUES = {"", "none", "null", "无", "无 docker", "无docker"}


class TaloError(RuntimeError):
    """User-facing Talo error."""


def get_talo_home() -> Path:
    configured = os.environ.get(TALO_HOME_ENV)
    return Path(configured).expanduser() if configured else DEFAULT_TALO_HOME


def config_path(talo_home: Optional[Path] = None) -> Path:
    return (talo_home or get_talo_home()) / "envs.yaml"


def usage_text() -> str:
    return """Usage:
  taloctl list
  taloctl <env> config
  taloctl <env> exec "<remote-command>"
  taloctl <env> docker "<command-in-project-workspace>"
  taloctl <env> ps
  taloctl <env> pull <remote-path> <local-path>
  taloctl <env> push <local-path> <remote-path>
  taloctl <env> sync

Examples:
  taloctl devbox config
  taloctl devbox sync
  taloctl devbox docker "npm test"
  taloctl devbox exec "hostname && pwd"
  taloctl devbox ps"""


def parse_simple_yaml(path: Path) -> Dict[str, Dict[str, str]]:
    if not path.exists():
        raise TaloError(f"config not found: {path}")

    envs: Dict[str, Dict[str, str]] = {}
    current: Optional[str] = None
    for lineno, raw in enumerate(path.read_text().splitlines(), start=1):
        current = parse_config_line(envs, current, lineno, raw)
    return envs


def parse_config_line(envs: Dict[str, Dict[str, str]], current: Optional[str], lineno: int, raw: str) -> Optional[str]:
    stripped = raw.strip()
    if not stripped or stripped.startswith("#"):
        return current
    if not raw.startswith((" ", "\t")):
        return parse_env_header(envs, lineno, raw, stripped)
    parse_env_value(envs, current, lineno, raw, stripped)
    return current


def parse_env_header(envs: Dict[str, Dict[str, str]], lineno: int, raw: str, stripped: str) -> str:
    if not stripped.endswith(":"):
        raise TaloError(f"invalid config line {lineno}: {raw}")
    name = stripped[:-1].strip()
    if not name:
        raise TaloError(f"empty environment name at line {lineno}")
    envs[name] = {}
    return name


def parse_env_value(
    envs: Dict[str, Dict[str, str]], current: Optional[str], lineno: int, raw: str, stripped: str
) -> None:
    if current is None:
        raise TaloError(f"key without environment at line {lineno}: {raw}")
    if ":" not in stripped:
        raise TaloError(f"invalid key/value line {lineno}: {raw}")
    key, value = stripped.split(":", 1)
    envs[current][key.strip()] = value.strip().strip('"').strip("'")


def load_env(name: str, path: Optional[Path] = None) -> Dict[str, str]:
    envs = parse_simple_yaml(path or config_path())
    if name not in envs:
        known = ", ".join(sorted(envs)) or "none"
        raise TaloError(f"unknown env: {name}; known envs: {known}")

    cfg = dict(envs[name])
    cfg.setdefault("host", name)
    cfg.setdefault("shell", "bash")
    validate_env(name, cfg)
    return cfg


def validate_env(name: str, cfg: Mapping[str, str]) -> None:
    missing = [key for key in ("host", "remote_base") if not cfg.get(key)]
    if missing:
        raise TaloError(f"env {name} missing required key(s): {', '.join(missing)}")


def command_string(parts: List[str]) -> str:
    if not parts:
        raise TaloError("missing command")
    if len(parts) == 1:
        return parts[0]
    return shlex.join(parts)


def local_root() -> Path:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return Path.cwd().resolve()
    return Path(proc.stdout.strip()).resolve() if proc.stdout.strip() else Path.cwd().resolve()


def runtime_env(env_name: str, cfg: Mapping[str, str], root: Optional[Path] = None) -> Dict[str, str]:
    resolved_root = (root or local_root()).resolve()
    project = resolved_root.name
    remote_base = cfg["remote_base"].rstrip("/")
    merged = os.environ.copy()
    merged.update(runtime_values(env_name, cfg, resolved_root, project, remote_base))
    return merged


def runtime_values(
    env_name: str, cfg: Mapping[str, str], root: Path, project: str, remote_base: str
) -> Dict[str, str]:
    return {
        "ENV_NAME": env_name,
        "HOST": cfg["host"],
        "REMOTE_BASE": remote_base,
        "LOCAL_ROOT": str(root),
        "PROJECT": project,
        "REMOTE_WORKSPACE": f"{remote_base}/.talo/workspaces/{project}",
        "CONTAINER": cfg.get("container", ""),
        "ENV_SHELL": cfg.get("shell", "bash") or "bash",
    }


def script_path(name: str, talo_home: Optional[Path] = None) -> Path:
    user_script = (talo_home or get_talo_home()) / "scripts" / name
    if user_script.exists():
        return user_script
    bundled = resources.files("talo.scripts").joinpath(name)
    if bundled.is_file():
        return Path(str(bundled))
    raise TaloError(f"script not found: {user_script}")


def run_script(name: str, env: Mapping[str, str]) -> int:
    return subprocess.run(["bash", str(script_path(name))], env=dict(env)).returncode


def is_none(value: str) -> bool:
    return value.strip().lower() in NONE_VALUES


def print_config(env_name: str, cfg: Mapping[str, str]) -> None:
    env = runtime_env(env_name, cfg)
    labels = {
        "HOST": "host",
        "REMOTE_BASE": "remote_base",
        "CONTAINER": "container",
        "ENV_SHELL": "shell",
        "LOCAL_ROOT": "local_root",
        "PROJECT": "project",
        "REMOTE_WORKSPACE": "remote_workspace",
    }
    print(f"env: {env_name}")
    for key, label in labels.items():
        print(f"{label}: {env[key]}")


def handle_list() -> int:
    envs = parse_simple_yaml(config_path())
    if not envs:
        print("No environments configured.")
        return 0
    for name in sorted(envs):
        cfg = envs[name]
        host = cfg.get("host", name)
        remote_base = cfg.get("remote_base", "")
        container = cfg.get("container", "")
        print(f"{name}\thost={host}\tremote_base={remote_base}\tcontainer={container}")
    return 0


def handle_action(env_name: str, action: str, rest: List[str]) -> int:
    cfg = load_env(env_name)
    env = runtime_env(env_name, cfg)
    if action == "config":
        print_config(env_name, cfg)
        return 0
    return handle_remote_action(action, rest, env)


def handle_remote_action(action: str, rest: List[str], env: Dict[str, str]) -> int:
    if action == "exec":
        env["REMOTE_CMD"] = command_string(rest)
        return run_script("remote_exec.sh", env)
    if action == "docker":
        return handle_docker(rest, env)
    if action == "ps":
        return run_script("docker_ps.sh", env)
    if action == "pull":
        return handle_transfer(rest, env, "pull_file.sh", "remote", "local")
    if action == "push":
        return handle_transfer(rest, env, "push_file.sh", "local", "remote")
    if action == "sync":
        return run_script("sync_code.sh", env)
    raise TaloError(f"unknown action: {action}")


def handle_docker(rest: List[str], env: Dict[str, str]) -> int:
    if is_none(env.get("CONTAINER", "")):
        raise TaloError("action 'docker' requires container in config")
    env["DOCKER_CMD"] = command_string(rest)
    return run_script("docker_exec.sh", env)


def handle_transfer(rest: List[str], env: Dict[str, str], script: str, first: str, second: str) -> int:
    if len(rest) != 2:
        raise TaloError(f"usage: taloctl <env> {script.split('_', 1)[0]} <{first}-path> <{second}-path>")
    env[f"{first.upper()}_PATH"] = rest[0]
    env[f"{second.upper()}_PATH"] = rest[1]
    return run_script(script, env)


def main(argv: List[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(usage_text())
        return 0
    if argv[0] == "list":
        return handle_list()
    if len(argv) < 2:
        print(usage_text(), file=sys.stderr)
        return 2
    env_name, action, *rest = argv
    return handle_action(env_name, action, rest)


def main_entry() -> int:
    try:
        return main(sys.argv[1:])
    except TaloError as exc:
        print(f"taloctl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main_entry())
