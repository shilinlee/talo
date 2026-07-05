from __future__ import annotations

import os
import platform
import posixpath
import re
import shlex
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from fnmatch import fnmatch
from importlib import metadata, resources
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Set

from talo import __version__

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
  taloctl version
  taloctl env list
  taloctl env show <name>
  taloctl env add <name> --host <host-or-ip-or-alias> --remote-base <path> [--container <name>] [--yes]
  taloctl env update <name> [--host <host-or-ip-or-alias>] [--remote-base <path>] [--container <name>] [--yes]
  taloctl <env> config
  taloctl <env> exec "<remote-command>"
  taloctl <env> docker "<command-in-project-workspace>"
  taloctl <env> ps
  taloctl <env> pull <remote-path> <local-path>
  taloctl <env> push <local-path> <remote-path>
  taloctl <env> sync

Examples:
  taloctl version
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


@dataclass
class EnvCommandOptions:
    name: str
    values: Dict[str, str]
    ssh_config: bool
    yes: bool
    user: str
    port: str
    identity_file: str


def load_envs_or_empty(path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    target = path or config_path()
    return parse_simple_yaml(target) if target.exists() else {}


def write_envs(envs: Mapping[str, Mapping[str, str]], path: Optional[Path] = None) -> None:
    target = path or config_path()
    backup_file(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    key_order = ["host", "remote_base", "container", "shell"]
    for name in sorted(envs):
        lines.append(f"{name}:")
        cfg = envs[name]
        for key in key_order:
            if key in cfg:
                lines.append(f"  {key}: {cfg[key]}")
        for key in sorted(k for k in cfg if k not in key_order):
            lines.append(f"  {key}: {cfg[key]}")
    target.write_text("\n".join(lines) + "\n")


def backup_file(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(f"{path.name}.bak.{stamp}")
    backup.write_bytes(path.read_bytes())


def parse_env_command_args(args: List[str], require_name: bool = True) -> EnvCommandOptions:
    if require_name:
        if not args:
            raise TaloError("usage: taloctl env add|update <name> [options]")
        name, rest = args[0], args[1:]
    else:
        name, rest = "", args
    values: Dict[str, str] = {}
    ssh_config = False
    yes = False
    user = ""
    port = "22"
    identity_file = ""
    flag_map = {
        "--host": "host",
        "--remote-base": "remote_base",
        "--container": "container",
        "--shell": "shell",
        "--user": "user",
        "--port": "port",
        "--identity-file": "identity_file",
    }
    index = 0
    while index < len(rest):
        token = rest[index]
        if token == "--yes":
            yes = True
            index += 1
            continue
        if token == "--ssh-config":
            ssh_config = True
            index += 1
            continue
        if token == "--no-ssh-config":
            ssh_config = False
            index += 1
            continue
        if token not in flag_map:
            raise TaloError(f"unknown env option: {token}")
        if index + 1 >= len(rest):
            raise TaloError(f"missing value for {token}")
        key = flag_map[token]
        value = rest[index + 1]
        if key == "user":
            user = value
        elif key == "port":
            port = value
        elif key == "identity_file":
            identity_file = value
        else:
            values[key] = value
        index += 2
    return EnvCommandOptions(name=name, values=values, ssh_config=ssh_config, yes=yes, user=user, port=port, identity_file=identity_file)


def validate_env_write_options(options: EnvCommandOptions, add: bool) -> None:
    if not options.yes:
        raise TaloError("env writes require --yes in this version")
    host = options.values.get("host", "")
    if host and "@" in host:
        raise TaloError("--host must be a host, IP, or SSH alias; pass --user separately, not user@host")
    if add:
        missing = [flag for flag, key in (("--host", "host"), ("--remote-base", "remote_base")) if not options.values.get(key)]
        if missing:
            raise TaloError(f"missing required option(s): {', '.join(missing)}")
    if options.ssh_config:
        missing = []
        if not options.values.get("host"):
            missing.append("--host")
        if not options.user:
            missing.append("--user")
        if missing:
            raise TaloError(f"--ssh-config requires: {', '.join(missing)}")
    if options.identity_file:
        identity = Path(options.identity_file).expanduser()
        if not identity.exists():
            raise TaloError(
                f"identity file not found: {options.identity_file}\n"
                "Generate a key pair first, for example:\n"
                f"  ssh-keygen -t ed25519 -f {options.identity_file} -C \"talo\""
            )


def handle_env_command(args: List[str]) -> int:
    if not args or args[0] in {"-h", "--help", "help"}:
        print(env_usage_text())
        return 0
    subcommand, rest = args[0], args[1:]
    try:
        if subcommand == "list":
            return handle_list()
        if subcommand == "show":
            if len(rest) != 1:
                raise TaloError("usage: taloctl env show <name>")
            cfg = load_env(rest[0])
            print_config(rest[0], cfg)
            return 0
        if subcommand == "add":
            return handle_env_add(rest)
        if subcommand == "update":
            return handle_env_update(rest)
        raise TaloError(f"unknown env subcommand: {subcommand}")
    except TaloError as exc:
        print(f"taloctl: {exc}", file=sys.stderr)
        return 1


def env_usage_text() -> str:
    return """Usage:
  taloctl env list
  taloctl env show <name>
  taloctl env add <name> --host <host-or-ip-or-alias> --remote-base <path> [--container <name>] [--shell bash] [--yes]
  taloctl env update <name> [--host <host-or-ip-or-alias>] [--remote-base <path>] [--container <name>] [--shell bash] [--yes]

SSH config options for add/update:
  --ssh-config --user <ssh-user> [--port 22] [--identity-file <path>]

Notes:
  --host does not accept user@host. Pass --user separately.
  --identity-file must already exist when provided."""


def handle_env_add(args: List[str]) -> int:
    options = parse_env_command_args(args)
    validate_env_write_options(options, add=True)
    envs = load_envs_or_empty()
    if options.name in envs:
        raise TaloError(f"env already exists: {options.name}; use taloctl env update {options.name}")
    cfg = dict(options.values)
    cfg.setdefault("shell", "bash")
    if options.ssh_config:
        cfg["host"] = options.name
    envs[options.name] = cfg
    if options.ssh_config:
        write_ssh_config(options)
    write_envs(envs)
    print(f"OK env added: {options.name}")
    return 0


def handle_env_update(args: List[str]) -> int:
    options = parse_env_command_args(args)
    validate_env_write_options(options, add=False)
    envs = load_envs_or_empty()
    if options.name not in envs:
        raise TaloError(f"env not found: {options.name}; use taloctl env add {options.name}")
    cfg = dict(envs[options.name])
    cfg.update(options.values)
    if options.ssh_config:
        cfg["host"] = options.name
    envs[options.name] = cfg
    if options.ssh_config:
        write_ssh_config(options)
    write_envs(envs)
    print(f"OK env updated: {options.name}")
    return 0


def write_ssh_config(options: EnvCommandOptions) -> None:
    ssh_dir = Path.home() / ".ssh"
    config = ssh_dir / "config"
    backup_file(config)
    ssh_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    block = ssh_config_block(options)
    existing = config.read_text() if config.exists() else ""
    updated = replace_or_append_host_block(existing, options.name, block)
    config.write_text(updated)
    try:
        ssh_dir.chmod(0o700)
        config.chmod(0o600)
    except OSError:
        pass


def ssh_config_block(options: EnvCommandOptions) -> str:
    lines = [
        f"Host {options.name}",
        f"  HostName {options.values['host']}",
        f"  User {options.user}",
        f"  Port {options.port}",
    ]
    if options.identity_file:
        lines.append(f"  IdentityFile {Path(options.identity_file).expanduser()}")
        lines.append("  IdentitiesOnly yes")
    lines.extend(
        [
            "  BatchMode yes",
            "  ControlMaster auto",
            "  ControlPath ~/.ssh/talo-%C",
            "  ControlPersist 10m",
            "  ServerAliveInterval 30",
            "  ServerAliveCountMax 3",
        ]
    )
    return "\n".join(lines) + "\n"


def replace_or_append_host_block(existing: str, host: str, block: str) -> str:
    pattern = re.compile(rf"(?ms)^Host\s+{re.escape(host)}\s*$.*?(?=^Host\s+|\Z)")
    if pattern.search(existing):
        updated = pattern.sub(block, existing.rstrip() + "\n")
    else:
        separator = "" if not existing or existing.endswith("\n") else "\n"
        updated = existing + separator + block
    return updated if updated.endswith("\n") else updated + "\n"


def is_none(value: str) -> bool:
    return value.strip().lower() in NONE_VALUES


def ssh_run(host: str, remote_cmd: str) -> int:
    return subprocess.run(["ssh", host, remote_cmd]).returncode


def quote_remote(value: str) -> str:
    return shlex.quote(value)


def remote_docker_exec_command(env: Mapping[str, str], command: str) -> str:
    workspace = quote_remote(env["REMOTE_WORKSPACE"])
    container = quote_remote(env["CONTAINER"])
    shell = quote_remote(env.get("ENV_SHELL", "bash") or "bash")
    docker_cmd = quote_remote(command)
    return f"docker exec -w {workspace} -i {container} {shell} -lc {docker_cmd}"


def remote_docker_ps_command() -> str:
    return "docker ps --format " + quote_remote("table {{.Names}}\t{{.Status}}\t{{.Image}}")


def sync_backend() -> str:
    return "sftp" if platform.system() == "Windows" else "rsync"


def ensure_paramiko_client(host: str):
    try:
        import paramiko  # type: ignore[import-not-found]
    except ImportError as exc:
        raise TaloError(
            "Windows native sync requires paramiko. Install with: python -m pip install 'talo[windows]' "
            "or python -m pip install paramiko"
        ) from exc

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh_config = load_ssh_config(paramiko, host)
    connect_kwargs = ssh_connect_kwargs(ssh_config, host)
    client.connect(**connect_kwargs)
    return client


def load_ssh_config(paramiko, host: str) -> Mapping[str, object]:
    config_path = Path.home() / ".ssh" / "config"
    if not config_path.exists():
        return {"hostname": host}
    cfg = paramiko.SSHConfig()
    with config_path.open() as fh:
        cfg.parse(fh)
    return cfg.lookup(host)


def ssh_connect_kwargs(ssh_config: Mapping[str, object], host: str) -> Dict[str, object]:
    kwargs: Dict[str, object] = {"hostname": str(ssh_config.get("hostname") or host)}
    if ssh_config.get("user"):
        kwargs["username"] = str(ssh_config["user"])
    if ssh_config.get("port"):
        kwargs["port"] = int(str(ssh_config["port"]))
    identity_file = ssh_config.get("identityfile")
    if isinstance(identity_file, list) and identity_file:
        kwargs["key_filename"] = [str(Path(item).expanduser()) for item in identity_file]
    return kwargs


def sync_windows_sftp(env: Mapping[str, str], ssh_factory: Optional[Callable[[], object]] = None) -> int:
    local = Path(env["LOCAL_ROOT"]).resolve()
    remote = normalize_remote_path(env["REMOTE_WORKSPACE"])
    if not local.is_dir():
        raise TaloError(f"sync_code: local root not found: {local}")

    print(f"sync_code: local_root={local}")
    print(f"sync_code: remote_workspace={env['HOST']}:{remote}")
    print("sync_code: backend=sftp")

    client = ssh_factory() if ssh_factory else ensure_paramiko_client(env["HOST"])
    sftp = None
    try:
        if ssh_factory:
            client.connect(env["HOST"])  # type: ignore[attr-defined]
        sftp = client.open_sftp()  # type: ignore[attr-defined]
        ensure_remote_dir(sftp, remote)
        local_files = collect_local_files(local)
        upload_changed_files(sftp, local, remote, local_files)
        delete_stale_remote_entries(sftp, remote, local_files)
    finally:
        if sftp is not None:
            sftp.close()
        client.close()  # type: ignore[attr-defined]
    print("sync_code: done")
    return 0


def normalize_remote_path(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized or "/"


def collect_local_files(root: Path) -> Set[str]:
    files: Set[str] = set()
    ignore_patterns = read_gitignore_patterns(root)
    for current_root, dirnames, filenames in os.walk(root):
        current = Path(current_root)
        rel_dir = relative_posix(root, current)
        dirnames[:] = [name for name in dirnames if not should_exclude(rel_join(rel_dir, name), True, ignore_patterns)]
        for name in filenames:
            rel = rel_join(rel_dir, name)
            if not should_exclude(rel, False, ignore_patterns):
                files.add(rel)
    return files


def read_gitignore_patterns(root: Path) -> List[str]:
    path = root / ".gitignore"
    if not path.exists():
        return []
    patterns = []
    for raw in path.read_text(errors="ignore").splitlines():
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and not stripped.startswith("!"):
            patterns.append(stripped)
    return patterns


def relative_posix(root: Path, path: Path) -> str:
    rel = path.relative_to(root).as_posix()
    return "" if rel == "." else rel


def rel_join(parent: str, name: str) -> str:
    return name if not parent else f"{parent}/{name}"


def should_exclude(rel: str, is_dir: bool, gitignore_patterns: List[str]) -> bool:
    parts = rel.split("/")
    if any(part in {".git", ".talo", ".envhub", ".talo-runs", ".envhub-runs", "node_modules", ".venv", "__pycache__"} for part in parts):
        return True
    rel_for_dir = f"{rel}/" if is_dir else rel
    for pattern in gitignore_patterns:
        normalized = pattern.strip("/")
        if pattern.endswith("/") and (rel == normalized or rel.startswith(f"{normalized}/")):
            return True
        if fnmatch(rel, normalized) or fnmatch(posixpath.basename(rel), normalized) or fnmatch(rel_for_dir, pattern):
            return True
    return False


def ensure_remote_dir(sftp, remote_dir: str) -> None:
    parts = [part for part in normalize_remote_path(remote_dir).split("/") if part]
    current = "/" if remote_dir.startswith("/") else ""
    for part in parts:
        current = posixpath.join(current, part) if current else part
        try:
            sftp.stat(current)
        except OSError:
            sftp.mkdir(current)


def upload_changed_files(sftp, local_root: Path, remote_root: str, local_files: Set[str]) -> None:
    for rel in sorted(local_files):
        local_path = local_root / Path(*rel.split("/"))
        remote_path = posixpath.join(remote_root, rel)
        ensure_remote_dir(sftp, posixpath.dirname(remote_path))
        local_stat = local_path.stat()
        if remote_file_matches(sftp, remote_path, local_stat):
            continue
        sftp.put(str(local_path), remote_path)
        if hasattr(sftp, "utime"):
            mtime = int(local_stat.st_mtime)
            sftp.utime(remote_path, (mtime, mtime))


def remote_file_matches(sftp, remote_path: str, local_stat: os.stat_result) -> bool:
    try:
        remote_stat = sftp.stat(remote_path)
    except OSError:
        return False
    if stat.S_ISDIR(remote_stat.st_mode):
        return False
    return remote_stat.st_size == local_stat.st_size and abs(int(remote_stat.st_mtime) - int(local_stat.st_mtime)) <= 1


def delete_stale_remote_entries(sftp, remote_root: str, local_files: Set[str]) -> None:
    for remote_path in sorted(list_remote_paths(sftp, remote_root), key=lambda p: p.count("/"), reverse=True):
        rel = posixpath.relpath(remote_path, remote_root)
        if rel == "." or rel in local_files:
            continue
        try:
            attrs = sftp.stat(remote_path)
        except OSError:
            continue
        if stat.S_ISDIR(attrs.st_mode):
            if any(path.startswith(f"{rel}/") for path in local_files):
                continue
            sftp.rmdir(remote_path)
        else:
            sftp.remove(remote_path)


def list_remote_paths(sftp, remote_dir: str) -> Set[str]:
    paths: Set[str] = set()
    try:
        attrs = sftp.listdir_attr(remote_dir)
    except OSError:
        return paths
    for attr in attrs:
        path = posixpath.join(remote_dir, attr.filename)
        paths.add(path)
        if stat.S_ISDIR(attr.st_mode):
            paths.update(list_remote_paths(sftp, path))
    return paths


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


def package_version() -> str:
    try:
        return metadata.version("talo")
    except metadata.PackageNotFoundError:
        return __version__


def git_commit() -> str:
    configured = os.environ.get("TALO_COMMIT")
    if configured:
        return configured
    try:
        proc = subprocess.run(
            ["git", "-C", str(Path(__file__).resolve().parent), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return "unknown"
    return proc.stdout.strip() or "unknown"


def handle_version() -> int:
    print(f"taloctl version: {package_version()}")
    print(f"commit: {git_commit()}")
    print(f"os: {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"python: {platform.python_version()} ({sys.executable})")
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
        return ssh_run(env["HOST"], command_string(rest))
    if action == "docker":
        return handle_docker(rest, env)
    if action == "ps":
        return ssh_run(env["HOST"], remote_docker_ps_command())
    if action == "pull":
        return handle_transfer(rest, env, "pull_file.sh", "remote", "local")
    if action == "push":
        return handle_transfer(rest, env, "push_file.sh", "local", "remote")
    if action == "sync":
        return handle_sync(env)
    raise TaloError(f"unknown action: {action}")


def handle_sync(env: Dict[str, str]) -> int:
    backend = sync_backend()
    if backend == "sftp":
        return sync_windows_sftp(env)
    if backend == "rsync":
        return run_script("sync_code.sh", env)
    raise TaloError(f"unknown sync backend: {backend}")


def handle_docker(rest: List[str], env: Dict[str, str]) -> int:
    if is_none(env.get("CONTAINER", "")):
        raise TaloError("action 'docker' requires container in config")
    return ssh_run(env["HOST"], remote_docker_exec_command(env, command_string(rest)))


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
    if argv[0] in {"version", "--version", "-V"}:
        return handle_version()
    if argv[0] == "env":
        return handle_env_command(argv[1:])
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
