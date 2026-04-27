from __future__ import annotations

from pathlib import Path
import signal
from threading import Event
from types import SimpleNamespace
from dataclasses import replace

import main
import pytest
import render_worker
import zenoh_worker


class FakeZenohWorker:
    def __init__(self) -> None:
        self.publish_frame_calls = 0
        self.published_frames: list[object | None] = []
        self.published_preview_camera_states: list[render_worker.PreviewCameraState] = []
        self.publish_operations: list[str] = []
        self.publish_current_state_calls = 0
        self.close_calls = 0
        self.publish_interval_s = 0.5
        self.updated_states: list[render_worker.RenderWorkerState] = []
        self.camera_offset = render_worker.CameraOffsetState()
        self.preview_ply_path = Path("/tmp/default-scene.ply")
        self.preview_focal_length_px = 900.0
        self.consume_camera_update_calls = 0

    def publish_frame(self, frame: object | None = None) -> None:
        self.publish_frame_calls += 1
        self.published_frames.append(frame)
        self.publish_operations.append("frame")

    def publish_preview_camera_state(
        self,
        state: render_worker.PreviewCameraState,
    ) -> None:
        self.published_preview_camera_states.append(state)
        self.publish_operations.append("camera_state")

    def publish_current_state(self) -> None:
        self.publish_current_state_calls += 1

    def update_state(self, state: render_worker.RenderWorkerState) -> None:
        self.updated_states.append(state)

    def consume_camera_update(self) -> bool:
        self.consume_camera_update_calls += 1
        return False

    def close(self) -> None:
        self.close_calls += 1


class FakeStopEvent:
    def __init__(self, wait_results: list[bool]) -> None:
        self.wait_results = list(wait_results)

    def wait(self, _timeout: float | None = None) -> bool:
        if not self.wait_results:
            raise AssertionError("wait called more times than expected")
        return self.wait_results.pop(0)


class FakeThread:
    def __init__(
        self,
        *,
        interrupt_on_first_join: bool = False,
        alive: bool = True,
    ) -> None:
        self.interrupt_on_first_join = interrupt_on_first_join
        self.alive = alive
        self.start_calls = 0
        self.join_calls: list[float | None] = []

    def start(self) -> None:
        self.start_calls += 1

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        if self.interrupt_on_first_join and timeout is None:
            self.interrupt_on_first_join = False
            raise KeyboardInterrupt()

    def is_alive(self) -> bool:
        return self.alive


def test_worker_threads_start_and_stop_cleanly() -> None:
    stop_event = Event()
    stop_event.set()
    fake_worker = FakeZenohWorker()

    command_thread, render_thread = main.build_worker_threads(stop_event=stop_event, worker=fake_worker)

    command_thread.start()
    render_thread.start()
    command_thread.join(timeout=1.0)
    render_thread.join(timeout=1.0)

    assert command_thread.name == "command-thread"
    assert render_thread.name == "render-thread"
    assert not command_thread.is_alive()
    assert not render_thread.is_alive()
    assert fake_worker.publish_frame_calls == 0
    assert fake_worker.publish_current_state_calls == 1
    assert fake_worker.close_calls == 0
    assert fake_worker.updated_states == []


def test_run_command_loop_publishes_until_stop_requested() -> None:
    stop_event = FakeStopEvent([False, False, True])
    fake_worker = FakeZenohWorker()

    main.run_command_loop(
        stop_event=stop_event,  # type: ignore[arg-type]
        worker=fake_worker,
    )

    assert fake_worker.publish_frame_calls == 0
    assert fake_worker.publish_current_state_calls == 3
    assert fake_worker.close_calls == 1


def test_publish_rendered_preview_frame_wraps_rgb_payload_for_transport() -> None:
    fake_worker = FakeZenohWorker()
    rendered_frame = render_worker.RenderedPreviewFrame(
        width=2,
        height=1,
        payload=b"\x01\x02\x03\x04\x05\x06",
    )

    main.publish_rendered_preview_frame(fake_worker, rendered_frame)

    assert fake_worker.publish_frame_calls == 1
    assert isinstance(fake_worker.published_frames[0], zenoh_worker.FrameMessage)
    frame_message = fake_worker.published_frames[0]
    assert frame_message.metadata.width == 2
    assert frame_message.metadata.height == 1
    assert frame_message.metadata.stride == 6
    assert frame_message.payload == rendered_frame.payload


def test_preview_publication_sequencer_publishes_matching_frame_and_camera_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_worker = FakeZenohWorker()
    sequencer = main.PreviewPublicationSequencer()
    preview_render = render_worker.PreviewRenderResult(
        frame=render_worker.RenderedPreviewFrame(
            width=2,
            height=1,
            payload=b"\x01\x02\x03\x04\x05\x06",
        ),
        camera_state=render_worker.PreviewCameraState(
            eye=(0.0, -10.0, 4.0),
            target=(0.0, 0.0, 0.0),
            up=(0.0, 0.0, 1.0),
            scene_center=(0.0, 0.0, 0.0),
            scene_radius=5.0,
            focal_length_px=900.0,
            image_width=2,
            image_height=1,
            world_up_axis="z",
            gizmo_enabled=True,
        ),
    )
    monkeypatch.setattr(main.zenoh_worker, "build_utc_timestamp", lambda: "2026-04-15T00:00:00Z")

    sequencer.publish(fake_worker, preview_render)
    sequencer.publish(fake_worker, replace(preview_render))

    assert fake_worker.publish_frame_calls == 2
    assert len(fake_worker.published_preview_camera_states) == 2
    first_frame = fake_worker.published_frames[0]
    second_frame = fake_worker.published_frames[1]
    first_camera_state = fake_worker.published_preview_camera_states[0]
    second_camera_state = fake_worker.published_preview_camera_states[1]
    assert isinstance(first_frame, zenoh_worker.FrameMessage)
    assert isinstance(second_frame, zenoh_worker.FrameMessage)
    assert first_frame.metadata.frame_id == 1
    assert second_frame.metadata.frame_id == 2
    assert first_frame.metadata.timestamp == "2026-04-15T00:00:00Z"
    assert second_frame.metadata.timestamp == "2026-04-15T00:00:00Z"
    assert first_camera_state.frame_id == 1
    assert second_camera_state.frame_id == 2
    assert first_camera_state.timestamp == "2026-04-15T00:00:00Z"
    assert second_camera_state.timestamp == "2026-04-15T00:00:00Z"
    assert fake_worker.publish_operations == [
        "frame",
        "camera_state",
        "frame",
        "camera_state",
    ]


def test_build_worker_threads_forwards_preview_scene_and_zoom_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_worker = FakeZenohWorker()
    fake_worker.preview_ply_path = Path("/tmp/scene.ply")
    fake_worker.preview_focal_length_px = 1234.0
    captured_args: dict[str, object] = {}

    def fake_render_gaussian_splat_preview_result(
        *,
        ply_path: Path,
        focal_length: float,
        camera_offset: render_worker.CameraOffsetState,
    ) -> render_worker.PreviewRenderResult:
        captured_args["ply_path"] = ply_path
        captured_args["focal_length"] = focal_length
        captured_args["camera_offset"] = camera_offset
        return render_worker.PreviewRenderResult(
            frame=render_worker.RenderedPreviewFrame(width=1, height=1, payload=b"\x00\x00\x00"),
            camera_state=render_worker.PreviewCameraState(),
        )

    monkeypatch.setattr(
        main,
        "render_gaussian_splat_preview_result",
        fake_render_gaussian_splat_preview_result,
    )

    _command_thread, render_thread = main.build_worker_threads(Event(), fake_worker)
    render_frame = render_thread._args[3]
    render_frame()

    assert captured_args == {
        "ply_path": Path("/tmp/scene.ply"),
        "focal_length": 1234.0,
        "camera_offset": render_worker.CameraOffsetState(),
    }


def test_restart_in_utf8_mode_if_needed_reexecutes_main_on_windows(monkeypatch) -> None:
    captured_command: dict[str, object] = {}

    def fake_run(command, check: bool, env: dict[str, str]):
        captured_command["command"] = command
        captured_command["check"] = check
        captured_command["env"] = env
        return SimpleNamespace(returncode=11)

    monkeypatch.setattr(main.os, "name", "nt")
    monkeypatch.setattr(main.sys, "executable", "python.exe")
    monkeypatch.setattr(main.sys, "flags", SimpleNamespace(utf8_mode=0))
    monkeypatch.setattr(main.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        main.restart_in_utf8_mode_if_needed(["--demo"])

    assert excinfo.value.code == 11
    assert captured_command["command"] == [
        "python.exe",
        "-X",
        "utf8",
        Path(main.__file__).resolve(),
        "--demo",
    ]
    assert captured_command["check"] is False
    assert captured_command["env"]["PYTHONUTF8"] == "1"


def test_main_stops_threads_when_keyboard_interrupt_is_raised(monkeypatch) -> None:
    captured_stop_event: dict[str, Event] = {}
    command_thread = FakeThread()
    render_thread = FakeThread()
    fake_worker = FakeZenohWorker()
    wait_calls = 0

    def fake_build_worker_threads(
        stop_event: Event,
        worker: FakeZenohWorker,
    ) -> tuple[FakeThread, FakeThread]:
        captured_stop_event["value"] = stop_event
        assert worker is fake_worker
        return command_thread, render_thread

    def fake_wait_for_threads(
        stop_event: Event,
        threads: tuple[FakeThread, FakeThread],
        poll_interval_s: float = main.THREAD_JOIN_POLL_INTERVAL_S,
        shutdown_join_timeout_s: float = main.THREAD_SHUTDOWN_JOIN_TIMEOUT_S,
    ) -> None:
        nonlocal wait_calls
        wait_calls += 1
        if wait_calls == 1:
            raise KeyboardInterrupt()

    monkeypatch.setattr(main, "build_worker_threads", fake_build_worker_threads)
    monkeypatch.setattr(main, "wait_for_threads", fake_wait_for_threads)

    assert main.main(zenoh_worker_factory=lambda: fake_worker) == 0
    assert captured_stop_event["value"].is_set()
    assert command_thread.start_calls == 1
    assert render_thread.start_calls == 1
    assert fake_worker.publish_current_state_calls == 1
    assert fake_worker.close_calls == 1
    assert wait_calls == 2


def test_build_signal_handler_sets_stop_event() -> None:
    stop_event = Event()

    handler = main.build_signal_handler(stop_event)
    handler(signal.SIGINT, None)

    assert stop_event.is_set()


def test_wait_for_threads_returns_after_shutdown_request() -> None:
    stop_event = Event()
    stop_event.set()
    command_thread = FakeThread(alive=True)
    render_thread = FakeThread(alive=True)

    main.wait_for_threads(
        stop_event,
        (command_thread, render_thread),
        poll_interval_s=0.01,
        shutdown_join_timeout_s=0.02,
    )

    assert command_thread.join_calls == [0.02]
    assert render_thread.join_calls == [0.02]
