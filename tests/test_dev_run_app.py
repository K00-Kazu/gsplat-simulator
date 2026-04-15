from __future__ import annotations

from pathlib import Path
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


if __name__ == "__main__":
    unittest.main()
