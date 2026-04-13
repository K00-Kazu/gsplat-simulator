#!/usr/bin/env python3
"""
Development runner for gsplat-simulator
Launches all components (UI, RenderWorker, Simulation Core) in tmux sessions
"""

import subprocess
import sys
import os
import time
from pathlib import Path


class TmuxSessionManager:
    """Manage tmux sessions for development"""

    def __init__(self, session_name="gsplat-dev"):
        self.session_name = session_name
        self.workspace_root = Path("/workspace")

    def check_tmux_installed(self):
        """Check if tmux is installed"""
        try:
            subprocess.run(["tmux", "-V"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("Error: tmux is not installed")
            print("Please install tmux: apt-get install tmux")
            return False

    def session_exists(self):
        """Check if tmux session already exists"""
        result = subprocess.run(
            ["tmux", "has-session", "-t", self.session_name],
            capture_output=True
        )
        return result.returncode == 0

    def kill_session(self):
        """Kill existing tmux session"""
        if self.session_exists():
            print(f"Killing existing tmux session: {self.session_name}")
            subprocess.run(["tmux", "kill-session", "-t", self.session_name])
            time.sleep(1)

    def create_session(self):
        """Create new tmux session"""
        print(f"Creating tmux session: {self.session_name}")
        subprocess.run([
            "tmux", "new-session",
            "-d",  # detached
            "-s", self.session_name,
            "-n", "ui",  # first window name
            "-c", str(self.workspace_root)
        ])

    def create_window(self, window_name, start_dir=None):
        """Create a new tmux window"""
        cmd = ["tmux", "new-window", "-t", f"{self.session_name}:", "-n", window_name]
        if start_dir:
            cmd.extend(["-c", str(start_dir)])
        subprocess.run(cmd)

    def send_keys(self, window_name, command, enter=True):
        """Send keys (command) to a tmux window"""
        target = f"{self.session_name}:{window_name}"
        subprocess.run(["tmux", "send-keys", "-t", target, command])
        if enter:
            subprocess.run(["tmux", "send-keys", "-t", target, "Enter"])

    def attach(self):
        """Attach to tmux session"""
        print(f"\nAttaching to tmux session: {self.session_name}")
        print("\nTmux shortcuts:")
        print("  Ctrl+b, 0/1/2  - Switch to window 0/1/2")
        print("  Ctrl+b, d      - Detach from session")
        print("  Ctrl+b, :kill-session - Kill session")
        print("\nPress Enter to attach...")
        input()
        os.execvp("tmux", ["tmux", "attach-session", "-t", self.session_name])


def check_prerequisites():
    """Check if all required components are built"""
    workspace = Path("/workspace")
    errors = []
    warnings = []

    # Check UI binary (try multiple possible locations)
    ui_binary_candidates = [
        workspace / "build/ui/apps/ui/gsplat_ui",  # CMake preset build location
        workspace / "build/ui/gsplat_ui",           # Alternative location
        workspace / "build/cmake/ui-linux-release/apps/ui/gsplat_ui",  # CMake preset with full path
    ]

    ui_binary = None
    for candidate in ui_binary_candidates:
        if candidate.exists():
            ui_binary = candidate
            break

    if not ui_binary:
        errors.append("UI binary not found in any of these locations:")
        for candidate in ui_binary_candidates:
            errors.append(f"  - {candidate}")
        errors.append("  Run: cmake --preset ui-linux-release && cmake --build --preset ui-linux-release")

    # Check Python venv
    venv_path = workspace / "apps/render/.venv"
    if not venv_path.exists():
        errors.append(f"Python venv not found: {venv_path}")
        errors.append("  Run: cd apps/render && python3 -m venv .venv")

    # Check RenderWorker main.py
    render_main = workspace / "apps/render/main.py"
    if not render_main.exists():
        errors.append(f"RenderWorker main.py not found: {render_main}")

    # Check Rust binary (search in target/release/)
    rust_binaries = list((workspace / "target/release").glob("*"))
    rust_executables = [
        b for b in rust_binaries
        if b.is_file() and os.access(b, os.X_OK) and not b.suffix and b.name not in ["build", "deps", "examples", "incremental"]
    ]

    if not rust_executables:
        warnings.append("No Rust executables found in target/release/")
        warnings.append("  Run: cargo build --release")
        warnings.append("  Simulation Core window will be available but not start automatically")

    # Display errors and warnings
    if errors:
        print("ERROR: Prerequisites not met:\n")
        for error in errors:
            print(f"  {error}")
        print("\nPlease build the required components first.")
        return False

    if warnings:
        print("WARNING:\n")
        for warning in warnings:
            print(f"  {warning}")
        print("\nContinuing anyway...\n")

    return True


def main():
    """Main entry point"""
    parser_help = """
    Usage: python dev_run_app.py [options]

    Options:
      start    - Start all components in tmux (default)
      stop     - Stop (kill) the tmux session
      attach   - Attach to existing session
      status   - Check status of tmux session
    """

    action = sys.argv[1] if len(sys.argv) > 1 else "start"

    manager = TmuxSessionManager()

    # Check tmux installation
    if not manager.check_tmux_installed():
        return 1

    # Handle different actions
    if action == "stop":
        manager.kill_session()
        print("Tmux session stopped.")
        return 0

    elif action == "attach":
        if not manager.session_exists():
            print(f"Error: Session '{manager.session_name}' does not exist.")
            print("Run 'python dev_run_app.py start' first.")
            return 1
        manager.attach()
        return 0

    elif action == "status":
        if manager.session_exists():
            print(f"Session '{manager.session_name}' is running.")
            subprocess.run(["tmux", "list-windows", "-t", manager.session_name])
        else:
            print(f"Session '{manager.session_name}' is not running.")
        return 0

    elif action == "start":
        # Check prerequisites
        if not check_prerequisites():
            return 1

        # Kill existing session if it exists
        if manager.session_exists():
            print(f"Session '{manager.session_name}' already exists.")
            response = input("Kill existing session and restart? [y/N]: ")
            if response.lower() != 'y':
                print("Aborted.")
                return 1
            manager.kill_session()

        # Create new session
        manager.create_session()

        # Window 0: UI
        print("Setting up UI window...")

        # Find UI binary
        workspace = Path("/workspace")
        ui_binary_candidates = [
            workspace / "build/ui/apps/ui/gsplat_ui",
            workspace / "build/ui/gsplat_ui",
            workspace / "build/cmake/ui-linux-release/apps/ui/gsplat_ui",
        ]

        ui_binary = None
        for candidate in ui_binary_candidates:
            if candidate.exists():
                ui_binary = candidate
                break

        manager.send_keys("ui", "cd /workspace")
        manager.send_keys("ui", "echo 'Starting UI...'")
        manager.send_keys("ui", "echo 'Checking DISPLAY: '$DISPLAY")

        if ui_binary:
            ui_binary_rel = ui_binary.relative_to(workspace)
            manager.send_keys("ui", f"./{ui_binary_rel}")
        else:
            manager.send_keys("ui", "echo 'ERROR: UI binary not found'")
            manager.send_keys("ui", "echo 'Expected locations:'")
            manager.send_keys("ui", "echo '  - build/ui/apps/ui/gsplat_ui'")
            manager.send_keys("ui", "echo '  - build/ui/gsplat_ui'")

        # Window 1: RenderWorker
        print("Setting up RenderWorker window...")
        manager.create_window("render", "/workspace/apps/render")
        manager.send_keys("render", "cd /workspace/apps/render")
        manager.send_keys("render", "source .venv/bin/activate")
        manager.send_keys("render", "echo 'Python venv activated'")
        manager.send_keys("render", "echo 'Starting RenderWorker...'")
        manager.send_keys("render", "echo 'Press Enter to start RenderWorker'")
        manager.send_keys("render", "python main.py", enter=False)

        # Window 2: Simulation Core
        print("Setting up Simulation Core window...")
        manager.create_window("core", "/workspace")
        manager.send_keys("core", "cd /workspace")

        # Find Rust executable
        rust_binaries = list(Path("/workspace/target/release").glob("*"))
        rust_executables = [
            b for b in rust_binaries
            if b.is_file() and os.access(b, os.X_OK) and not b.suffix and b.name not in ["build", "deps", "examples", "incremental"]
        ]

        if rust_executables:
            # Use pre-built binary
            rust_bin = rust_executables[0]
            manager.send_keys("core", f"echo 'Found Simulation Core binary: {rust_bin.name}'")
            manager.send_keys("core", f"./{rust_bin.relative_to('/workspace')}", enter=False)
            manager.send_keys("core", "  # Press Enter to start")
        else:
            # Use cargo run if binary not found
            manager.send_keys("core", "echo 'No pre-built Rust executable found'")
            manager.send_keys("core", "echo 'Will use: cargo run --release'")
            manager.send_keys("core", "echo 'This may take time to compile on first run...'")
            manager.send_keys("core", "cargo run --release", enter=False)
            manager.send_keys("core", "  # Press Enter to build and start")

        print("\nTmux session created successfully!")
        print(f"Session name: {manager.session_name}")
        print("\nWindows:")
        print("  0: ui     - Qt UI Application")
        print("  1: render - Python RenderWorker")
        print("  2: core   - Rust Simulation Core")

        # Attach to session
        manager.attach()
        return 0

    else:
        print(parser_help)
        return 1


if __name__ == "__main__":
    sys.exit(main())
