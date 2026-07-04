from __future__ import annotations

import os
import tempfile
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

    def test_command_string_quotes_multiple_parts(self) -> None:
        self.assertEqual(cli.command_string(["python", "-m", "pytest"]), "python -m pytest")


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


if __name__ == "__main__":
    unittest.main()
