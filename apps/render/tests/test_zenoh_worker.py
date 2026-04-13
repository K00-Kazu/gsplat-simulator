from __future__ import annotations

import json
from pathlib import Path

import zenoh_worker


class FakePublisher:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object]] = []
        self.undeclare_calls = 0

    def put(self, payload: object, *, encoding: object | None = None) -> None:
        self.calls.append((payload, encoding))

    def undeclare(self) -> None:
        self.undeclare_calls += 1


class FakeSession:
    def __init__(self) -> None:
        self.close_calls = 0
        self.declare_calls: list[tuple[str, object]] = []
        self.declare_subscriber_calls: list[str] = []

    def declare_publisher(self, key_expr: str, *, encoding: object | None = None) -> FakePublisher:
        self.declare_calls.append((key_expr, encoding))
        return FakePublisher()

    def declare_subscriber(self, key_expr: str, handler=None) -> FakePublisher:
        self.declare_subscriber_calls.append(key_expr)
        return FakePublisher()

    def close(self) -> None:
        self.close_calls += 1


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


def test_parse_camera_offset_payload_reads_expected_fields() -> None:
    assert zenoh_worker.parse_camera_offset_payload(
        '{"offset_x":0.5,"offset_y":0.0,"offset_z":-0.25}'
    ) == zenoh_worker.CameraOffsetState(
        offset_x=0.5,
        offset_y=0.0,
        offset_z=-0.25,
    )


def test_update_state_publishes_each_new_lifecycle_once() -> None:
    publisher = FakePublisher()
    session = FakeSession()
    worker = zenoh_worker.ZenohWorker(
        state=zenoh_worker.RenderWorkerState(),
        session=session,
        publisher=publisher,
        publish_interval_s=1.0,
    )

    worker.update_state(
        zenoh_worker.RenderWorkerState(zenoh_worker.RenderLifecycleState.LOADING)
    )
    worker.update_state(
        zenoh_worker.RenderWorkerState(zenoh_worker.RenderLifecycleState.LOADING)
    )
    worker.update_state(
        zenoh_worker.RenderWorkerState(zenoh_worker.RenderLifecycleState.RENDERING)
    )

    assert worker.state == zenoh_worker.RenderWorkerState(
        zenoh_worker.RenderLifecycleState.RENDERING
    )
    assert publisher.calls == [
        ('{"state":"Loading"}', zenoh_worker.zenoh.Encoding.APPLICATION_JSON),
        ('{"state":"Rendering"}', zenoh_worker.zenoh.Encoding.APPLICATION_JSON),
    ]


def test_apply_camera_offset_marks_update_pending_once_per_distinct_value() -> None:
    publisher = FakePublisher()
    session = FakeSession()
    worker = zenoh_worker.ZenohWorker(
        state=zenoh_worker.RenderWorkerState(),
        session=session,
        publisher=publisher,
        publish_interval_s=1.0,
    )

    worker.apply_camera_offset(zenoh_worker.CameraOffsetState(offset_x=0.25))
    worker.apply_camera_offset(zenoh_worker.CameraOffsetState(offset_x=0.25))

    assert worker.camera_offset == zenoh_worker.CameraOffsetState(offset_x=0.25)
    assert worker.consume_camera_update() is True
    assert worker.consume_camera_update() is False


def test_update_state_publishes_completed_state_without_implicit_frame_publish() -> None:
    state_publisher = FakePublisher()
    metadata_publisher = FakePublisher()
    payload_publisher = FakePublisher()
    session = FakeSession()
    worker = zenoh_worker.ZenohWorker(
        state=zenoh_worker.RenderWorkerState(),
        session=session,
        publisher=state_publisher,
        publish_interval_s=1.0,
        frame_metadata_publisher=metadata_publisher,
        frame_payload_publisher=payload_publisher,
    )

    worker.update_state(
        zenoh_worker.RenderWorkerState(zenoh_worker.RenderLifecycleState.COMPLETED)
    )
    worker.update_state(
        zenoh_worker.RenderWorkerState(zenoh_worker.RenderLifecycleState.COMPLETED)
    )

    assert state_publisher.calls == [
        ('{"state":"Completed"}', zenoh_worker.zenoh.Encoding.APPLICATION_JSON),
    ]
    assert metadata_publisher.calls == []
    assert payload_publisher.calls == []


def test_publish_frame_publishes_metadata_and_red_payload() -> None:
    state_publisher = FakePublisher()
    metadata_publisher = FakePublisher()
    payload_publisher = FakePublisher()
    session = FakeSession()
    worker = zenoh_worker.ZenohWorker(
        state=zenoh_worker.RenderWorkerState(),
        session=session,
        publisher=state_publisher,
        publish_interval_s=1.0,
        frame_metadata_publisher=metadata_publisher,
        frame_payload_publisher=payload_publisher,
    )

    worker.publish_frame()

    assert state_publisher.calls == []
    assert metadata_publisher.calls == [
        (
            '{"frame_id":1,"timestamp":"2026-04-08T00:00:00Z","width":4,"height":2,"stride":12,"pixel_format":"rgb8"}',
            zenoh_worker.zenoh.Encoding.APPLICATION_JSON,
        ),
    ]
    assert payload_publisher.calls == [
        (
            b"\xff\x00\x00" * 8,
            zenoh_worker.zenoh.Encoding.APPLICATION_OCTET_STREAM,
        ),
    ]


def test_build_frame_message_from_rgb8_payload_preserves_dimensions_and_bytes() -> None:
    frame_message = zenoh_worker.build_frame_message_from_rgb8_payload(
        b"\x01\x02\x03\x04\x05\x06",
        width=2,
        height=1,
        frame_id=9,
        timestamp="2026-04-12T00:00:00Z",
    )

    assert frame_message.metadata == zenoh_worker.FrameMetadata(
        frame_id=9,
        timestamp="2026-04-12T00:00:00Z",
        width=2,
        height=1,
        stride=6,
        pixel_format="rgb8",
    )
    assert frame_message.payload == b"\x01\x02\x03\x04\x05\x06"


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
    captured_config_paths: list[Path] = []
    session = FakeSession()
    config = object()
    topic_key_exprs = zenoh_worker.TopicKeyExprs(
        state="simulation/render/response/state",
        frame_metadata="simulation/core/frame_metadata",
        frame_payload="simulation/core/frame_payload",
        camera_request="simulation/render/request/camera",
    )

    def fake_open(config: object) -> FakeSession:
        assert config is fake_config
        return session

    def fake_build_config(path: Path) -> object:
        captured_config_paths.append(path)
        return fake_config

    def fake_load_publish_interval_s(path: Path) -> float:
        captured_config_paths.append(path)
        return 0.25

    def fake_load_topic_key_exprs(path: Path) -> zenoh_worker.TopicKeyExprs:
        captured_config_paths.append(path)
        return topic_key_exprs

    fake_config = config
    monkeypatch.setattr(zenoh_worker, "build_config", fake_build_config)
    monkeypatch.setattr(zenoh_worker, "load_publish_interval_s", fake_load_publish_interval_s)
    monkeypatch.setattr(zenoh_worker, "load_topic_key_exprs", fake_load_topic_key_exprs)
    monkeypatch.setattr(zenoh_worker.zenoh, "open", fake_open)

    worker = zenoh_worker.ZenohWorker.create()

    assert worker.state == zenoh_worker.RenderWorkerState()
    assert worker.publish_interval_s == 0.25
    assert session.declare_calls == [
        (
            topic_key_exprs.state,
            zenoh_worker.zenoh.Encoding.APPLICATION_JSON,
        ),
        (
            topic_key_exprs.frame_metadata,
            zenoh_worker.zenoh.Encoding.APPLICATION_JSON,
        ),
        (
            topic_key_exprs.frame_payload,
            zenoh_worker.zenoh.Encoding.APPLICATION_OCTET_STREAM,
        ),
    ]
    assert captured_config_paths == [
        zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH,
        zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH,
        zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH,
    ]
    assert session.declare_subscriber_calls == [
        topic_key_exprs.camera_request,
    ]


def test_default_transport_config_path_points_to_repo_config() -> None:
    expected_suffix = Path("config") / "transport.dev.json"

    assert zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH.is_file()
    assert zenoh_worker.DEFAULT_TRANSPORT_CONFIG_PATH.as_posix().endswith(
        expected_suffix.as_posix()
    )


def test_load_topic_key_exprs_reads_transport_topics(tmp_path: Path) -> None:
    config_path = tmp_path / "transport.dev.json"
    config_path.write_text(
        json.dumps(
            {
                "zenoh": {},
                "topics": {
                    "core": {
                        "frame_metadata": "simulation/core/frame_metadata",
                        "frame_payload": "simulation/core/frame_payload",
                    },
                    "render": {
                        "request": "simulation/render/request/**",
                        "camera_request": "simulation/render/request/camera",
                        "response": "simulation/render/response/**",
                        "state": "simulation/render/response/state",
                    },
                },
                "timeouts": {
                    "publish_interval_ms": 1000,
                },
            }
        ),
        encoding="utf-8",
    )

    assert zenoh_worker.load_topic_key_exprs(config_path) == zenoh_worker.TopicKeyExprs(
        state="simulation/render/response/state",
        frame_metadata="simulation/core/frame_metadata",
        frame_payload="simulation/core/frame_payload",
        camera_request="simulation/render/request/camera",
    )
