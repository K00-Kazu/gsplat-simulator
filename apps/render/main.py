from __future__ import annotations

import signal
from threading import Event, Thread
from types import FrameType
from typing import Callable, Protocol, Sequence

from render_worker import run_render_loop
from zenoh_worker import ZenohWorker


class CommandWorker(Protocol):
    @property
    def publish_interval_s(self) -> float:
        """Return the state publish interval in seconds."""

    def publish_current_state(self) -> None:
        """Publish the current worker state."""

    def close(self) -> None:
        """Release transport resources."""


ZenohWorkerFactory = Callable[[], CommandWorker]
SignalHandler = Callable[[int, FrameType | None], None]

THREAD_JOIN_POLL_INTERVAL_S = 0.1
THREAD_SHUTDOWN_JOIN_TIMEOUT_S = 1.0


def run_command_loop(
    stop_event: Event,
    zenoh_worker_factory: ZenohWorkerFactory = ZenohWorker.create,
) -> None:
    worker = zenoh_worker_factory()

    try:
        while True:
            worker.publish_current_state()
            if stop_event.wait(worker.publish_interval_s):
                break
    finally:
        worker.close()


def build_worker_threads(
    stop_event: Event,
    zenoh_worker_factory: ZenohWorkerFactory = ZenohWorker.create,
) -> tuple[Thread, Thread]:
    command_thread = Thread(
        target=run_command_loop,
        name="command-thread",
        args=(stop_event, zenoh_worker_factory),
        daemon=True,
    )
    render_thread = Thread(
        target=run_render_loop,
        name="render-thread",
        args=(stop_event,),
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


def main() -> int:
    stop_event = Event()
    previous_handlers = install_signal_handlers(stop_event)
    threads = build_worker_threads(stop_event=stop_event)

    try:
        print("Render worker started. Press Ctrl+C to stop.", flush=True)

        for thread in threads:
            thread.start()

        wait_for_threads(stop_event, threads)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        wait_for_threads(stop_event, threads)
        restore_signal_handlers(previous_handlers)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
