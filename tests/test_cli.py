from __future__ import annotations

import errno
import os
import stat
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest import mock

from talo import cli


class ConfigParsingTests(unittest.TestCase):
    def test_parse_simple_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envs.yaml"
            path.write_text(
                "devbox:\n"
                "  host: devbox.example\n"
                "  remote_base: /home/devuser\n"
                "  container: dev-container\n"
                "  shell: bash\n"
            )

            envs = cli.parse_simple_yaml(path)

        self.assertEqual(envs["devbox"]["host"], "devbox.example")
        self.assertEqual(envs["devbox"]["remote_base"], "/home/devuser")

    def test_load_env_defaults_host_and_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "envs.yaml"
            path.write_text("lab:\n  remote_base: /remote\n")

            cfg = cli.load_env("lab", path)

        self.assertEqual(cfg["host"], "lab")
        self.assertEqual(cfg["shell"], "bash")


class RuntimeEnvTests(unittest.TestCase):
    def test_runtime_env_derives_talo_workspace(self) -> None:
        root = Path("/tmp/project")
        cfg = {"host": "server", "remote_base": "/home/alice", "shell": "bash", "container": "dev"}

        env = cli.runtime_env("lab", cfg, root=root)

        self.assertEqual(env["PROJECT"], "project")
        self.assertEqual(env["REMOTE_WORKSPACE"], "/home/alice/.talo/workspaces/project")

    def test_git_runtime_env_uses_branch_workspace(self) -> None:
        root = Path("/tmp/project")
        cfg = {"host": "server", "remote_base": "/home/alice", "shell": "bash", "container": "dev"}
        with mock.patch("talo.cli.is_git_repo", return_value=True), mock.patch(
            "talo.cli.current_branch", return_value="feature/foo bar"
        ):
            env = cli.runtime_env("lab", cfg, root=root)

        self.assertEqual(env["PROJECT"], "project")
        self.assertEqual(env["REMOTE_WORKSPACE"], "/home/alice/workspace/worktress/project/feature-foo-bar")

    def test_safe_branch_name(self) -> None:
        self.assertEqual(cli.safe_branch_name("feature/foo bar"), "feature-foo-bar")
        self.assertEqual(cli.safe_branch_name("..."), "branch")

    def test_command_string_quotes_multiple_parts(self) -> None:
        self.assertEqual(cli.command_string(["python", "-m", "pytest"]), "python -m pytest")


class FakeSftpAttr:
    def __init__(self, filename: str, mode: int, size: int = 0, mtime: int = 0) -> None:
        self.filename = filename
        self.st_mode = mode
        self.st_size = size
        self.st_mtime = mtime


class FakeSftp:
    def __init__(self) -> None:
        self.dirs = {
            "/remote/project",
            "/remote/project/keep",
            "/remote/project/.git",
            "/remote/project/.talo",
            "/remote/project/node_modules",
            "/remote/project/node_modules/pkg",
            "/remote/project/.venv",
            "/remote/project/.venv/bin",
        }
        self.files = {
            "/remote/project/same.txt": (b"same", 1_700_000_000),
            "/remote/project/changed.txt": (b"old", 1),
            "/remote/project/stale.txt": (b"stale", 1),
            "/remote/project/keep/nested.txt": (b"nested", 1_700_000_001),
            "/remote/project/.git/config": (b"git", 1),
            "/remote/project/.talo/state": (b"state", 1),
            "/remote/project/node_modules/pkg/index.js": (b"pkg", 1),
            "/remote/project/.venv/bin/python": (b"python", 1),
        }
        self.operations: list[tuple[str, str]] = []
        self.closed = False

    def _norm(self, path: str) -> str:
        return path.replace("\\", "/").rstrip("/") or "/"

    def stat(self, path: str):
        path = self._norm(path)
        if path in self.files:
            data, mtime = self.files[path]
            return FakeSftpAttr(Path(path).name, stat.S_IFREG | 0o644, len(data), mtime)
        if path in self.dirs:
            return FakeSftpAttr(Path(path).name, stat.S_IFDIR | 0o755)
        raise FileNotFoundError(errno.ENOENT, path)

    def mkdir(self, path: str) -> None:
        path = self._norm(path)
        self.dirs.add(path)
        self.operations.append(("mkdir", path))

    def put(self, local_path: str, remote_path: str) -> None:
        remote_path = self._norm(remote_path)
        data = Path(local_path).read_bytes()
        self.files[remote_path] = (data, int(Path(local_path).stat().st_mtime))
        self.operations.append(("put", remote_path))

    def utime(self, remote_path: str, times: tuple[int, int]) -> None:
        remote_path = self._norm(remote_path)
        data, _ = self.files[remote_path]
        self.files[remote_path] = (data, int(times[1]))
        self.operations.append(("utime", remote_path))

    def listdir_attr(self, path: str):
        path = self._norm(path)
        prefix = path.rstrip("/") + "/"
        seen = set()
        attrs = []
        for directory in self.dirs:
            if directory.startswith(prefix):
                child = directory[len(prefix) :].split("/", 1)[0]
                if child and child not in seen:
                    seen.add(child)
                    attrs.append(FakeSftpAttr(child, stat.S_IFDIR | 0o755))
        for file_path, (data, mtime) in self.files.items():
            if file_path.startswith(prefix):
                child = file_path[len(prefix) :].split("/", 1)[0]
                if child and child not in seen:
                    seen.add(child)
                    attrs.append(FakeSftpAttr(child, stat.S_IFREG | 0o644, len(data), mtime))
        return attrs

    def remove(self, path: str) -> None:
        path = self._norm(path)
        del self.files[path]
        self.operations.append(("remove", path))

    def rmdir(self, path: str) -> None:
        path = self._norm(path)
        self.dirs.remove(path)
        self.operations.append(("rmdir", path))

    def close(self) -> None:
        self.closed = True


class FakeSshClient:
    def __init__(self, sftp: FakeSftp) -> None:
        self.sftp = sftp
        self.connected_host = None
        self.closed = False

    def connect(self, hostname: str) -> None:
        self.connected_host = hostname

    def open_sftp(self) -> FakeSftp:
        return self.sftp

    def close(self) -> None:
        self.closed = True


class RemoteActionTests(unittest.TestCase):
    def test_bootstrap_clones_when_remote_workspace_is_missing(self) -> None:
        env = {"HOST": "devbox", "LOCAL_ROOT": "/tmp/project", "REMOTE_WORKSPACE": "/remote/workspace"}
        with mock.patch("talo.cli.is_git_repo", return_value=True), mock.patch(
            "talo.cli.current_branch", return_value="main"
        ), mock.patch("talo.cli.origin_url", return_value="git@example.com:org/repo.git"), mock.patch(
            "talo.cli.remote_dir_is_empty_or_missing", return_value=True
        ), mock.patch("talo.cli.ssh_run", return_value=0) as fake_ssh_run, mock.patch(
            "talo.cli.run_sync_overlay", return_value=0
        ) as fake_overlay:
            code = cli.handle_remote_action("bootstrap", [], env)

        self.assertEqual(code, 0)
        self.assertEqual(fake_ssh_run.call_count, 1)
        remote_cmd = fake_ssh_run.call_args.args[1]
        self.assertIn("mkdir -p /remote", remote_cmd)
        self.assertIn("git clone --branch main git@example.com:org/repo.git /remote/workspace", remote_cmd)
        fake_overlay.assert_called_once_with(env)

    def test_bootstrap_rejects_non_empty_remote_workspace(self) -> None:
        env = {"HOST": "devbox", "LOCAL_ROOT": "/tmp/project", "REMOTE_WORKSPACE": "/remote/workspace"}
        with mock.patch("talo.cli.is_git_repo", return_value=True), mock.patch(
            "talo.cli.current_branch", return_value="main"
        ), mock.patch("talo.cli.origin_url", return_value="git@example.com:org/repo.git"), mock.patch(
            "talo.cli.remote_dir_is_empty_or_missing", return_value=False
        ):
            with self.assertRaises(cli.TaloError):
                cli.handle_bootstrap(env)

    def test_sync_checks_remote_git_before_overlay(self) -> None:
        env = {"HOST": "devbox", "LOCAL_ROOT": "/tmp/project", "REMOTE_WORKSPACE": "/remote/workspace"}
        with mock.patch("talo.cli.is_git_repo", return_value=True), mock.patch(
            "talo.cli.current_branch", return_value="main"
        ), mock.patch("talo.cli.remote_git_ready") as fake_ready, mock.patch(
            "talo.cli.run_sync_overlay", return_value=0
        ) as fake_overlay:
            code = cli.handle_sync(env)

        self.assertEqual(code, 0)
        fake_ready.assert_called_once_with(env, "main")
        fake_overlay.assert_called_once_with(env)

    def test_sync_rejects_remote_branch_mismatch(self) -> None:
        env = {"HOST": "devbox", "REMOTE_WORKSPACE": "/remote/workspace"}
        with mock.patch("talo.cli.remote_path_is_dir", side_effect=[True, True]), mock.patch(
            "talo.cli.remote_current_branch", return_value="other"
        ):
            with self.assertRaises(cli.TaloError):
                cli.remote_git_ready(env, "main")

    def test_exec_uses_ssh_without_local_bash_script(self) -> None:
        with mock.patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0

            code = cli.handle_remote_action(
                "exec", ["hostname && pwd"], {"HOST": "devbox", "REMOTE_WORKSPACE": "/remote/project"}
            )

        self.assertEqual(code, 0)
        fake_run.assert_called_once_with(["ssh", "devbox", "hostname && pwd"])

    def test_docker_builds_remote_docker_exec_command_without_local_bash_script(self) -> None:
        env = {
            "HOST": "devbox",
            "CONTAINER": "dev-container",
            "REMOTE_WORKSPACE": "/remote/project",
            "ENV_SHELL": "bash",
        }
        with mock.patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0

            code = cli.handle_remote_action("docker", ["python", "-m", "pytest"], env)

        self.assertEqual(code, 0)
        remote_cmd = "docker exec -w /remote/project -i dev-container bash -lc 'python -m pytest'"
        fake_run.assert_called_once_with(["ssh", "devbox", remote_cmd])

    def test_windows_sync_uses_paramiko_sftp_incrementally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            same = root / "same.txt"
            same.write_text("same")
            os.utime(same, (1_700_000_000, 1_700_000_000))
            changed = root / "changed.txt"
            changed.write_text("new")
            keep = root / "keep" / "nested.txt"
            keep.parent.mkdir()
            keep.write_text("nested")
            os.utime(keep, (1_700_000_001, 1_700_000_001))
            ignored = root / ".git" / "config"
            ignored.parent.mkdir()
            ignored.write_text("ignore me")
            env = {"HOST": "devbox", "LOCAL_ROOT": str(root), "REMOTE_WORKSPACE": "/remote/project"}
            sftp = FakeSftp()
            ssh = FakeSshClient(sftp)

            code = cli.sync_windows_sftp(env, ssh_factory=lambda: ssh)

        self.assertEqual(code, 0)
        self.assertEqual(ssh.connected_host, "devbox")
        self.assertTrue(sftp.closed)
        self.assertTrue(ssh.closed)
        self.assertIn(("put", "/remote/project/changed.txt"), sftp.operations)
        self.assertNotIn(("put", "/remote/project/same.txt"), sftp.operations)
        self.assertNotIn(("put", "/remote/project/.git/config"), sftp.operations)
        self.assertIn(("remove", "/remote/project/stale.txt"), sftp.operations)
        self.assertNotIn(("remove", "/remote/project/.git/config"), sftp.operations)
        self.assertNotIn(("remove", "/remote/project/.talo/state"), sftp.operations)
        self.assertNotIn(("remove", "/remote/project/node_modules/pkg/index.js"), sftp.operations)
        self.assertNotIn(("remove", "/remote/project/.venv/bin/python"), sftp.operations)
        self.assertNotIn(("rmdir", "/remote/project/.git"), sftp.operations)
        self.assertNotIn(("rmdir", "/remote/project/.talo"), sftp.operations)
        self.assertNotIn(("rmdir", "/remote/project/node_modules"), sftp.operations)
        self.assertNotIn(("rmdir", "/remote/project/.venv"), sftp.operations)
        self.assertNotIn(("rmdir", "/remote/project/keep"), sftp.operations)
        self.assertEqual(sftp.files["/remote/project/changed.txt"][0], b"new")

    def test_ps_uses_ssh_without_local_bash_script(self) -> None:
        with mock.patch("subprocess.run") as fake_run:
            fake_run.return_value.returncode = 0

            code = cli.handle_remote_action("ps", [], {"HOST": "devbox"})

        self.assertEqual(code, 0)
        called = fake_run.call_args.args[0]
        self.assertEqual(called[0:2], ["ssh", "devbox"])
        self.assertIn("docker ps --format", called[2])

    def test_sync_backend_is_selected_by_platform_only(self) -> None:
        with mock.patch("platform.system", return_value="Windows"):
            self.assertEqual(cli.sync_backend(), "sftp")
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertEqual(cli.sync_backend(), "rsync")
        with mock.patch("platform.system", return_value="Linux"):
            self.assertEqual(cli.sync_backend(), "rsync")


class EnvCommandTests(unittest.TestCase):
    def test_env_add_writes_talo_config_without_ssh_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            talo_home = Path(tmp) / "talo"
            home.mkdir()
            with mock.patch.dict(os.environ, {"HOME": str(home), cli.TALO_HOME_ENV: str(talo_home)}):
                code = cli.main(
                    [
                        "env",
                        "add",
                        "devbox",
                        "--host",
                        "devbox.example",
                        "--remote-base",
                        "/home/devuser",
                        "--container",
                        "dev-container",
                        "--yes",
                    ]
                )

            self.assertEqual(code, 0)
            cfg = cli.parse_simple_yaml(talo_home / "envs.yaml")
            self.assertEqual(cfg["devbox"]["host"], "devbox.example")
            self.assertEqual(cfg["devbox"]["remote_base"], "/home/devuser")
            self.assertEqual(cfg["devbox"]["container"], "dev-container")
            self.assertEqual(cfg["devbox"]["shell"], "bash")
            self.assertFalse((home / ".ssh" / "config").exists())

    def test_env_add_rejects_user_at_host_without_guessing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            talo_home = Path(tmp) / "talo"
            with mock.patch.dict(os.environ, {cli.TALO_HOME_ENV: str(talo_home)}):
                with mock.patch("sys.stderr"):
                    code = cli.main(
                        [
                            "env",
                            "add",
                            "devbox",
                            "--host",
                            "devuser@devbox.example",
                            "--remote-base",
                            "/home/devuser",
                            "--yes",
                        ]
                    )

            self.assertEqual(code, 1)
            self.assertFalse((talo_home / "envs.yaml").exists())

    def test_env_add_with_ssh_config_checks_identity_file_and_writes_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            talo_home = Path(tmp) / "talo"
            identity = home / ".ssh" / "id_ed25519"
            identity.parent.mkdir(parents=True)
            identity.write_text("private-key")
            with mock.patch.dict(os.environ, {"HOME": str(home), cli.TALO_HOME_ENV: str(talo_home)}):
                code = cli.main(
                    [
                        "env",
                        "add",
                        "devbox",
                        "--host",
                        "devbox.example",
                        "--user",
                        "devuser",
                        "--port",
                        "2222",
                        "--identity-file",
                        str(identity),
                        "--remote-base",
                        "/home/devuser",
                        "--ssh-config",
                        "--yes",
                    ]
                )

            self.assertEqual(code, 0)
            cfg = cli.parse_simple_yaml(talo_home / "envs.yaml")
            self.assertEqual(cfg["devbox"]["host"], "devbox")
            ssh_config = (home / ".ssh" / "config").read_text()
            self.assertIn("Host devbox\n", ssh_config)
            self.assertIn("  HostName devbox.example\n", ssh_config)
            self.assertIn("  User devuser\n", ssh_config)
            self.assertIn("  Port 2222\n", ssh_config)
            self.assertIn(f"  IdentityFile {identity}\n", ssh_config)
            self.assertIn("  IdentitiesOnly yes\n", ssh_config)
            self.assertIn("  BatchMode yes\n", ssh_config)
            self.assertIn("  ControlMaster auto\n", ssh_config)
            self.assertIn("  ControlPath ~/.ssh/talo-%C\n", ssh_config)
            self.assertIn("  ControlPersist 10m\n", ssh_config)
            self.assertIn("  ServerAliveInterval 30\n", ssh_config)
            self.assertIn("  ServerAliveCountMax 3\n", ssh_config)
            self.assertNotIn("StrictHostKeyChecking", ssh_config)

    def test_env_add_fails_when_identity_file_is_missing_and_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            talo_home = Path(tmp) / "talo"
            home.mkdir()
            missing_identity = home / ".ssh" / "missing"
            with mock.patch.dict(os.environ, {"HOME": str(home), cli.TALO_HOME_ENV: str(talo_home)}):
                with mock.patch("sys.stderr"):
                    code = cli.main(
                        [
                            "env",
                            "add",
                            "devbox",
                            "--host",
                            "devbox.example",
                            "--user",
                            "devuser",
                            "--identity-file",
                            str(missing_identity),
                            "--remote-base",
                            "/home/devuser",
                            "--ssh-config",
                            "--yes",
                        ]
                    )

            self.assertEqual(code, 1)
            self.assertFalse((talo_home / "envs.yaml").exists())
            self.assertFalse((home / ".ssh" / "config").exists())

    def test_env_update_requires_existing_env_and_merges_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            talo_home = Path(tmp) / "talo"
            talo_home.mkdir()
            (talo_home / "envs.yaml").write_text(
                "devbox:\n"
                "  host: old.example\n"
                "  remote_base: /home/old\n"
                "  container: old-container\n"
                "  shell: bash\n"
            )
            with mock.patch.dict(os.environ, {cli.TALO_HOME_ENV: str(talo_home)}):
                code = cli.main(["env", "update", "devbox", "--container", "new-container", "--yes"])

            self.assertEqual(code, 0)
            cfg = cli.parse_simple_yaml(talo_home / "envs.yaml")
            self.assertEqual(cfg["devbox"]["host"], "old.example")
            self.assertEqual(cfg["devbox"]["remote_base"], "/home/old")
            self.assertEqual(cfg["devbox"]["container"], "new-container")

    def test_env_list_and_show_are_aliases_for_existing_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            talo_home = Path(tmp) / "talo"
            talo_home.mkdir()
            (talo_home / "envs.yaml").write_text("devbox:\n  host: devbox.example\n  remote_base: /home/devuser\n")
            with mock.patch.dict(os.environ, {cli.TALO_HOME_ENV: str(talo_home)}):
                with mock.patch("builtins.print") as fake_print:
                    list_code = cli.main(["env", "list"])
                list_output = "\n".join(call.args[0] for call in fake_print.call_args_list)
                with mock.patch("builtins.print") as fake_print:
                    show_code = cli.main(["env", "show", "devbox"])
                show_output = "\n".join(call.args[0] for call in fake_print.call_args_list)

            self.assertEqual(list_code, 0)
            self.assertIn("devbox\thost=devbox.example", list_output)
            self.assertEqual(show_code, 0)
            self.assertIn("env: devbox", show_output)
            self.assertIn("remote_base: /home/devuser", show_output)


class PackagingTests(unittest.TestCase):
    def test_paramiko_dependency_is_windows_only(self) -> None:
        pyproject = tomllib.loads(Path("pyproject.toml").read_text())
        dependencies = pyproject["project"]["dependencies"]
        self.assertIn("paramiko>=3.0; platform_system == 'Windows'", dependencies)
        self.assertEqual(pyproject["project"]["optional-dependencies"]["windows"], ["paramiko>=3.0"])


class MainTests(unittest.TestCase):
    def test_list_uses_talo_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            home.mkdir(exist_ok=True)
            (home / "envs.yaml").write_text("lab:\n  host: remote\n  remote_base: /remote\n")
            with mock.patch.dict(os.environ, {cli.TALO_HOME_ENV: str(home)}):
                with mock.patch("builtins.print") as fake_print:
                    code = cli.main(["list"])

        self.assertEqual(code, 0)
        fake_print.assert_called_once_with("lab\thost=remote\tremote_base=/remote\tcontainer=")

    def test_version_prints_runtime_information(self) -> None:
        with mock.patch("builtins.print") as fake_print:
            code = cli.main(["version"])

        self.assertEqual(code, 0)
        output = "\n".join(call.args[0] for call in fake_print.call_args_list)
        self.assertIn("taloctl version:", output)
        self.assertIn("commit:", output)
        self.assertIn("os:", output)
        self.assertIn("python:", output)


if __name__ == "__main__":
    unittest.main()
