from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import dev_run_app


class FakeTmuxSessionManager:
    latest_instance: "FakeTmuxSessionManager | None" = None

    def __init__(self, session_name: str = "gsplat-dev") -> None:
        self.session_name = session_name
        self.workspace_root = Path("/workspace")
        self.send_key_calls: list[tuple[str, str, bool]] = []
        self.created_windows: list[tuple[str, str | None]] = []
        self.created_session = False
        self.attached = False
        FakeTmuxSessionManager.latest_instance = self

    def check_tmux_installed(self) -> bool:
        return True

    def session_exists(self) -> bool:
        return False

    def kill_session(self) -> None:
        raise AssertionError("kill_session should not be called")

    def create_session(self) -> None:
        self.created_session = True

    def create_window(self, window_name: str, start_dir: str | None = None) -> None:
        self.created_windows.append((window_name, start_dir))

    def send_keys(self, window_name: str, command: str, enter: bool = True) -> None:
        self.send_key_calls.append((window_name, command, enter))

    def attach(self) -> None:
        self.attached = True


class DevRunAppTest(unittest.TestCase):
    def test_start_autoruns_render_worker_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            ui_binary = tmp_path / "build/ui/apps/ui/gsplat_ui"
            ui_binary.parent.mkdir(parents=True, exist_ok=True)
            ui_binary.write_text("", encoding="utf-8")

            original_path = Path

            def fake_path(value: str | Path) -> Path:
                resolved = original_path(value)
                try:
                    relative = resolved.relative_to("/workspace")
                except ValueError:
                    return resolved
                return tmp_path / relative

            with patch.object(dev_run_app, "Path", new=fake_path), \
                patch.object(dev_run_app, "TmuxSessionManager", FakeTmuxSessionManager), \
                patch.object(dev_run_app, "check_prerequisites", return_value=True), \
                patch.object(dev_run_app.sys, "argv", ["dev_run_app.py", "start"]):
                result = dev_run_app.main()

        self.assertEqual(result, 0)
        manager = FakeTmuxSessionManager.latest_instance
        self.assertIsNotNone(manager)
        self.assertTrue(manager.created_session)
        self.assertTrue(manager.attached)
        self.assertIn(("render", "python main.py", True), manager.send_key_calls)
        self.assertNotIn(
            ("render", "echo 'Press Enter to start RenderWorker'", True),
            manager.send_key_calls,
        )

    def test_build_runs_expected_commands_without_tmux(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            render_dir = tmp_path / "apps/render"
            render_dir.mkdir(parents=True, exist_ok=True)
            (render_dir / "requirements.txt").write_text("numpy<2.0.0\n", encoding="utf-8")

            original_path = Path
            commands: list[tuple[list[str], str | None, bool]] = []

            def fake_path(value: str | Path) -> Path:
                resolved = original_path(value)
                try:
                    relative = resolved.relative_to("/workspace")
                except ValueError:
                    return resolved
                return tmp_path / relative

            def fake_run(command, cwd=None, check=False, **kwargs):
                normalized_command = [str(part) for part in command]
                commands.append((normalized_command, str(cwd) if cwd is not None else None, check))

                if normalized_command[:3] == [dev_run_app.sys.executable, "-m", "venv"]:
                    venv_python = tmp_path / "apps/render/.venv/bin/python"
                    venv_python.parent.mkdir(parents=True, exist_ok=True)
                    venv_python.write_text("", encoding="utf-8")

                return subprocess.CompletedProcess(command, 0)

            with patch.object(dev_run_app, "Path", new=fake_path), \
                patch.object(dev_run_app, "TmuxSessionManager", side_effect=AssertionError("tmux should not be used for build")), \
                patch.object(dev_run_app.subprocess, "run", side_effect=fake_run), \
                patch.object(dev_run_app.sys, "argv", ["dev_run_app.py", "build"]):
                result = dev_run_app.main()

        self.assertEqual(result, 0)
        self.assertEqual(
            commands,
            [
                ([dev_run_app.sys.executable, "-m", "venv", ".venv"], str(tmp_path / "apps/render"), True),
                ([str(tmp_path / "apps/render/.venv/bin/python"), "-m", "pip", "install", "--upgrade", "pip"], str(tmp_path / "apps/render"), True),
                ([str(tmp_path / "apps/render/.venv/bin/python"), "-m", "pip", "install", "-r", "requirements.txt"], str(tmp_path / "apps/render"), True),
                (["cargo", "build", "--release"], str(tmp_path), True),
                (["cmake", "--preset", "ui-linux-release"], str(tmp_path), True),
                (["cmake", "--build", "--preset", "ui-linux-release"], str(tmp_path), True),
            ],
        )

    def test_build_skips_venv_creation_when_python_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            render_dir = tmp_path / "apps/render"
            render_dir.mkdir(parents=True, exist_ok=True)
            (render_dir / "requirements.txt").write_text("numpy<2.0.0\n", encoding="utf-8")
            venv_python = tmp_path / "apps/render/.venv/bin/python"
            venv_python.parent.mkdir(parents=True, exist_ok=True)
            venv_python.write_text("", encoding="utf-8")

            original_path = Path
            commands: list[list[str]] = []

            def fake_path(value: str | Path) -> Path:
                resolved = original_path(value)
                try:
                    relative = resolved.relative_to("/workspace")
                except ValueError:
                    return resolved
                return tmp_path / relative

            def fake_run(command, cwd=None, check=False, **kwargs):
                commands.append([str(part) for part in command])
                return subprocess.CompletedProcess(command, 0)

            with patch.object(dev_run_app, "Path", new=fake_path), \
                patch.object(dev_run_app.subprocess, "run", side_effect=fake_run), \
                patch.object(dev_run_app.sys, "argv", ["dev_run_app.py", "build"]):
                result = dev_run_app.main()

        self.assertEqual(result, 0)
        self.assertNotIn([dev_run_app.sys.executable, "-m", "venv", ".venv"], commands)

    def test_build_returns_nonzero_when_a_step_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            tmp_path = Path(temp_dir)
            render_dir = tmp_path / "apps/render"
            render_dir.mkdir(parents=True, exist_ok=True)
            (render_dir / "requirements.txt").write_text("numpy<2.0.0\n", encoding="utf-8")

            original_path = Path

            def fake_path(value: str | Path) -> Path:
                resolved = original_path(value)
                try:
                    relative = resolved.relative_to("/workspace")
                except ValueError:
                    return resolved
                return tmp_path / relative

            def fake_run(command, cwd=None, check=False, **kwargs):
                normalized_command = [str(part) for part in command]
                if normalized_command[:3] == [dev_run_app.sys.executable, "-m", "venv"]:
                    venv_python = tmp_path / "apps/render/.venv/bin/python"
                    venv_python.parent.mkdir(parents=True, exist_ok=True)
                    venv_python.write_text("", encoding="utf-8")
                if normalized_command == ["cargo", "build", "--release"]:
                    raise subprocess.CalledProcessError(2, command)
                return subprocess.CompletedProcess(command, 0)

            with patch.object(dev_run_app, "Path", new=fake_path), \
                patch.object(dev_run_app.subprocess, "run", side_effect=fake_run), \
                patch.object(dev_run_app.sys, "argv", ["dev_run_app.py", "build"]):
                result = dev_run_app.main()

        self.assertEqual(result, 2)


if __name__ == "__main__":
    unittest.main()
