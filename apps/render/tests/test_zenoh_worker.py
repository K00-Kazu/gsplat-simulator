from __future__ import annotations

from pathlib import Path

import zenoh_worker


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.undeclare_calls = 0

    def put(self, payload: str, *, encoding: object | None = None) -> None:
        self.calls.append((payload, encoding))

    def undeclare(self) -> None:
        self.undeclare_calls += 1


class FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0
        self.declare_calls: list[tuple[str, object]] = []

    def declare_publisher(self, key_expr: str, *, encoding: object | None = None) -> FakePublisher:
        self.declare_calls.append((key_expr, encoding))
        return FakePublisher()

    def close(self) -> None:
        self.close_calls += 1


class FakeConfig:
    def __init__(self, publish_interval_ms: int = 1000) -> None:
        self.publish_interval_ms = publish_interval_ms

    def get_json(self, key: str) -> str:
        assert key == "timeouts/publish_interval_ms"
        return str(self.publish_interval_ms)


def test_publish_current_state_publishes_idle_payload() -> None:
    publisher = FakePublisher()
    session = FakeSession()
    worker = zenoh_worker.ZenohWorker(
        state=zenoh_worker.RenderWorkerState(),
        session=session,
        publisher=publisher,
        publish_interval_s=1.0,
    )

    worker.publish_current_state()

    assert publisher.calls == [
        ('{"state":"Idle"}', zenoh_worker.zenoh.Encoding.APPLICATION_JSON),
    ]


def test_close_releases_publisher_and_session() -> None:
    publisher = FakePublisher()
    session = FakeSession()
    worker = zenoh_worker.ZenohWorker(
        state=zenoh_worker.RenderWorkerState(),
        session=session,
        publisher=publisher,
        publish_interval_s=1.0,
    )

    worker.close()

    assert publisher.undeclare_calls == 1
    assert session.close_calls == 1


def test_create_initializes_idle_state_and_json_publisher(monkeypatch) -> None:
    captured_config_paths: list[str] = []
    session = FakeSession()
    config = FakeConfig(publish_interval_ms=250)

    def fake_open(config: object) -> FakeSession:
        assert config is fake_config
        return session

    def fake_from_file(path: str) -> FakeConfig:
        captured_config_paths.append(path)
        return fake_config

    fake_config = config
    monkeypatch.setattr(zenoh_worker.zenoh.Config, "from_file", fake_from_file)
    monkeypatch.setattr(zenoh_worker.zenoh, "open", fake_open)

    worker = zenoh_worker.ZenohWorker.create()

    assert worker.state == zenoh_worker.RenderWorkerState()
    assert worker.publish_interval_s == 0.25
    assert session.declare_calls == [
        (
            zenoh_worker.DEFAULT_STATE_KEY_EXPR,
            zenoh_worker.zenoh.Encoding.APPLICATION_JSON,
        ),
    ]
    assert captured_config_paths == [str(zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH)]


def test_default_transport_config_path_points_to_repo_config() -> None:
    expected_suffix = Path("config") / "transport.dev.json5"

    assert zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH.is_file()
    assert zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH.as_posix().endswith(
        expected_suffix.as_posix()
    )
