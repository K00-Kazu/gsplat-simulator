from __future__ import annotations

import signal
from threading import Event

import main


class FakeZenohWorker:
    def __init__(self) -> None:
        self.publish_calls = 0
        self.close_calls = 0
        self.publish_interval_s = 0.5

    def publish_current_state(self) -> None:
        self.publish_calls += 1

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

    command_thread, render_thread = main.build_worker_threads(
        stop_event=stop_event,
        zenoh_worker_factory=lambda: fake_worker,
    )

    command_thread.start()
    render_thread.start()
    command_thread.join(timeout=1.0)
    render_thread.join(timeout=1.0)

    assert command_thread.name == "command-thread"
    assert render_thread.name == "render-thread"
    assert not command_thread.is_alive()
    assert not render_thread.is_alive()
    assert fake_worker.publish_calls == 1
    assert fake_worker.close_calls == 1


def test_run_command_loop_publishes_until_stop_requested() -> None:
    stop_event = FakeStopEvent([False, False, True])
    fake_worker = FakeZenohWorker()

    main.run_command_loop(
        stop_event=stop_event,  # type: ignore[arg-type]
        zenoh_worker_factory=lambda: fake_worker,
    )

    assert fake_worker.publish_calls == 3
    assert fake_worker.close_calls == 1


def test_main_stops_threads_when_keyboard_interrupt_is_raised(monkeypatch) -> None:
    captured_stop_event: dict[str, Event] = {}
    command_thread = FakeThread()
    render_thread = FakeThread()
    wait_calls = 0

    def fake_build_worker_threads(
        stop_event: Event,
        zenoh_worker_factory=main.ZenohWorker.create,
    ) -> tuple[FakeThread, FakeThread]:
        captured_stop_event["value"] = stop_event
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

    assert main.main() == 0
    assert captured_stop_event["value"].is_set()
    assert command_thread.start_calls == 1
    assert render_thread.start_calls == 1
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
