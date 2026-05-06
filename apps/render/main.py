from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import replace
from itertools import count
from pathlib import Path
from threading import Event, Thread
from types import FrameType
from typing import Callable, Protocol, Sequence

import zenoh_worker
from render_worker import (
    CameraOffsetState,
    PreviewCameraState,
    PreviewRenderResult,
    RenderWorkerState,
    RenderedPreviewFrame,
    RobotState,
    render_gaussian_splat_preview_result,
    run_render_loop,
)
from zenoh_worker import ZenohWorker, build_frame_message_from_rgb8_payload


class CommandWorker(Protocol):
    @property
    def publish_interval_s(self) -> float:
        """Return the publish interval in seconds."""

    def publish_frame(self, frame: object | None = None) -> None:
        """Publish the current frame."""

    def publish_preview_camera_state(self, state: PreviewCameraState) -> None:
        """Publish the current preview camera state."""

    def publish_current_state(self) -> None:
        """Publish the current render worker state."""

    def update_state(self, state: RenderWorkerState) -> None:
        """Publish a render worker state transition when it changes."""

    @property
    def camera_offset(self) -> CameraOffsetState:
        """Return the latest preview camera pan/orbit request."""

    @property
    def preview_ply_path(self) -> Path:
        """Return the active preview scene asset path."""

    @property
    def preview_focal_length_px(self) -> float:
        """Return the active preview focal length in pixels."""

    @property
    def robot_states(self) -> tuple[RobotState, ...]:
        """Return the configured robots with their latest poses."""

    def consume_camera_update(self) -> bool:
        """Return whether a new camera update should trigger re-rendering."""

    def close(self) -> None:
        """Release transport resources."""


ZenohWorkerFactory = Callable[[], CommandWorker]
SignalHandler = Callable[[int, FrameType | None], None]

THREAD_JOIN_POLL_INTERVAL_S = 0.1
THREAD_SHUTDOWN_JOIN_TIMEOUT_S = 1.0


def restart_in_utf8_mode_if_needed(argv: Sequence[str]) -> None:
    if os.name != "nt" or sys.flags.utf8_mode:
        return

    completed_process = subprocess.run(
        [sys.executable, "-X", "utf8", Path(__file__).resolve(), *argv],
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    raise SystemExit(completed_process.returncode)


def publish_rendered_preview_frame(
    worker: CommandWorker,
    frame: RenderedPreviewFrame,
) -> None:
    worker.publish_frame(
        build_frame_message_from_rgb8_payload(
            payload=frame.payload,
            width=frame.width,
            height=frame.height,
        )
    )


class PreviewPublicationSequencer:
    def __init__(self, start_frame_id: int = 1) -> None:
        self._frame_ids = count(start_frame_id)

    def publish(
        self,
        worker: CommandWorker,
        preview_render: PreviewRenderResult,
    ) -> None:
        frame_id = next(self._frame_ids)
        timestamp = zenoh_worker.build_utc_timestamp()
        published_camera_state = replace(
            preview_render.camera_state,
            frame_id=frame_id,
            timestamp=timestamp,
        )
        worker.publish_frame(
            build_frame_message_from_rgb8_payload(
                payload=preview_render.frame.payload,
                width=preview_render.frame.width,
                height=preview_render.frame.height,
                frame_id=frame_id,
                timestamp=timestamp,
            )
        )
        worker.publish_preview_camera_state(published_camera_state)


def run_command_loop(
    stop_event: Event,
    worker: CommandWorker,
    close_worker: bool = True,
) -> None:
    try:
        while True:
            worker.publish_current_state()
            if stop_event.wait(worker.publish_interval_s):
                break
    finally:
        if close_worker:
            worker.close()


def build_worker_threads(
    stop_event: Event,
    worker: CommandWorker,
) -> tuple[Thread, Thread]:
    preview_publication_sequencer = PreviewPublicationSequencer()
    command_thread = Thread(
        target=run_command_loop,
        name="command-thread",
        args=(stop_event, worker, False),
        daemon=True,
    )
    render_thread = Thread(
        target=run_render_loop,
        name="render-thread",
        args=(
            stop_event,
            worker.update_state,
            None,
            lambda: render_gaussian_splat_preview_result(
                ply_path=worker.preview_ply_path,
                focal_length=worker.preview_focal_length_px,
                camera_offset=worker.camera_offset,
                robot_states=worker.robot_states,
            ),
            lambda preview_render: preview_publication_sequencer.publish(worker, preview_render),
            worker.consume_camera_update,
        ),
        daemon=True,
    )
    return command_thread, render_thread


def build_signal_handler(stop_event: Event) -> SignalHandler:
    def handle_signal(_signum: int, _frame: FrameType | None) -> None:
        if not stop_event.is_set():
            print("Shutdown requested. Stopping render worker...", flush=True)
        stop_event.set()

    return handle_signal


def install_signal_handlers(stop_event: Event) -> dict[signal.Signals, object]:
    handler = build_signal_handler(stop_event)
    installed_handlers: dict[signal.Signals, object] = {}

    for signal_name in ("SIGINT", "SIGTERM"):
        signal_value = getattr(signal, signal_name, None)
        if signal_value is None:
            continue

        installed_handlers[signal_value] = signal.getsignal(signal_value)
        signal.signal(signal_value, handler)

    return installed_handlers


def restore_signal_handlers(previous_handlers: dict[signal.Signals, object]) -> None:
    for signal_value, handler in previous_handlers.items():
        signal.signal(signal_value, handler)


def wait_for_threads(
    stop_event: Event,
    threads: Sequence[Thread],
    poll_interval_s: float = THREAD_JOIN_POLL_INTERVAL_S,
    shutdown_join_timeout_s: float = THREAD_SHUTDOWN_JOIN_TIMEOUT_S,
) -> None:
    while not stop_event.is_set():
        if not any(thread.is_alive() for thread in threads):
            return

        for thread in threads:
            thread.join(timeout=poll_interval_s)

    for thread in threads:
        if thread.is_alive():
            thread.join(timeout=shutdown_join_timeout_s)


def main(zenoh_worker_factory: ZenohWorkerFactory = ZenohWorker.create) -> int:
    stop_event = Event()
    previous_handlers = install_signal_handlers(stop_event)
    worker = zenoh_worker_factory()
    threads = build_worker_threads(stop_event=stop_event, worker=worker)

    try:
        print("Render worker started. Press Ctrl+C to stop.", flush=True)
        worker.publish_current_state()

        for thread in threads:
            thread.start()

        wait_for_threads(stop_event, threads)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        wait_for_threads(stop_event, threads)
        worker.close()
        restore_signal_handlers(previous_handlers)

    return 0


if __name__ == "__main__":
    restart_in_utf8_mode_if_needed(sys.argv[1:])
    raise SystemExit(main())
