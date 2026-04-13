from __future__ import annotations

import json
from datetime import datetime, timezone
from dataclasses import dataclass
import math
from pathlib import Path
from threading import Lock

import zenoh

from render_worker import CameraOffsetState, RenderLifecycleState, RenderWorkerState


DEFAULT_TRANSPORT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "transport.dev.json"
)
DEFAULT_CAMERA_REQUEST_KEY_EXPR = "simulation/render/request/camera"

DEFAULT_TEST_FRAME_ID = 1
DEFAULT_TEST_FRAME_TIMESTAMP = "2026-04-08T00:00:00Z"
DEFAULT_TEST_FRAME_WIDTH = 4
DEFAULT_TEST_FRAME_HEIGHT = 2
DEFAULT_TEST_FRAME_PIXEL_FORMAT = "rgb8"

RGB8_BYTES_PER_PIXEL = 3
SOLID_RED_RGB8_PIXEL = b"\xff\x00\x00"


@dataclass(frozen=True)
class FrameMetadata:
    frame_id: int
    timestamp: str
    width: int
    height: int
    stride: int
    pixel_format: str


@dataclass(frozen=True)
class FrameMessage:
    metadata: FrameMetadata
    payload: bytes


@dataclass(frozen=True)
class TopicKeyExprs:
    state: str
    frame_metadata: str
    frame_payload: str
    camera_request: str


def serialize_state(state: RenderWorkerState) -> str:
    return json.dumps({"state": state.lifecycle.value}, separators=(",", ":"))


def serialize_frame_metadata(metadata: FrameMetadata) -> str:
    return json.dumps(
        {
            "frame_id": metadata.frame_id,
            "timestamp": metadata.timestamp,
            "width": metadata.width,
            "height": metadata.height,
            "stride": metadata.stride,
            "pixel_format": metadata.pixel_format,
        },
        separators=(",", ":"),
    )


def load_transport_config(config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH) -> dict[str, object]:
    return json.loads(config_path.read_text(encoding="utf-8"))


def require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def require_string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def resolve_render_state_key_expr(render_topics: dict[str, object]) -> str:
    state_key_expr = render_topics.get("state")
    if isinstance(state_key_expr, str) and state_key_expr:
        return state_key_expr

    response_key_expr = require_string(
        render_topics.get("response"),
        "topics.render.response",
    )
    if not response_key_expr.endswith("/**"):
        raise ValueError(
            "topics.render.state must be configured when topics.render.response is not a wildcard"
        )

    return f"{response_key_expr[:-3]}/state"


def resolve_render_camera_request_key_expr(render_topics: dict[str, object]) -> str:
    camera_request_key_expr = render_topics.get("camera_request")
    if isinstance(camera_request_key_expr, str) and camera_request_key_expr:
        return camera_request_key_expr

    request_key_expr = require_string(
        render_topics.get("request"),
        "topics.render.request",
    )
    if not request_key_expr.endswith("/**"):
        raise ValueError(
            "topics.render.camera_request must be configured when topics.render.request is not a wildcard"
        )

    return f"{request_key_expr[:-3]}/camera"


def build_config(config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH) -> zenoh.Config:
    raw = load_transport_config(config_path)
    zenoh_section = raw["zenoh"]
    return zenoh.Config.from_json5(json.dumps(zenoh_section))


def load_publish_interval_s(config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH) -> float:
    raw = load_transport_config(config_path)
    publish_interval_ms = raw["timeouts"]["publish_interval_ms"]
    return float(publish_interval_ms) / 1000.0


def load_topic_key_exprs(
    config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH,
) -> TopicKeyExprs:
    raw = load_transport_config(config_path)
    topics = require_mapping(raw.get("topics"), "topics")
    core_topics = require_mapping(topics.get("core"), "topics.core")
    render_topics = require_mapping(topics.get("render"), "topics.render")

    return TopicKeyExprs(
        state=resolve_render_state_key_expr(render_topics),
        frame_metadata=require_string(
            core_topics.get("frame_metadata"),
            "topics.core.frame_metadata",
        ),
        frame_payload=require_string(
            core_topics.get("frame_payload"),
            "topics.core.frame_payload",
        ),
        camera_request=resolve_render_camera_request_key_expr(render_topics),
    )


def require_float(value: object, path: str) -> float:
    if not isinstance(value, (float, int)):
        raise ValueError(f"{path} must be a number")
    resolved_value = float(value)
    if not math.isfinite(resolved_value):
        raise ValueError(f"{path} must be finite")
    return resolved_value


def parse_camera_offset_payload(payload: str) -> CameraOffsetState:
    raw = json.loads(payload)
    if not isinstance(raw, dict):
        raise ValueError("camera payload must be a JSON object")

    return CameraOffsetState(
        offset_x=require_float(raw.get("offset_x"), "offset_x"),
        offset_y=require_float(raw.get("offset_y"), "offset_y"),
        offset_z=require_float(raw.get("offset_z"), "offset_z"),
    )


def build_rgb8_stride(width: int) -> int:
    if width < 1:
        raise ValueError("width must be positive")
    return width * RGB8_BYTES_PER_PIXEL


def build_solid_red_payload(
    width: int,
    height: int,
    pixel_format: str = DEFAULT_TEST_FRAME_PIXEL_FORMAT,
) -> bytes:
    if width < 1:
        raise ValueError("width must be positive")
    if height < 1:
        raise ValueError("height must be positive")
    if pixel_format != DEFAULT_TEST_FRAME_PIXEL_FORMAT:
        raise ValueError(f"unsupported pixel format: {pixel_format}")

    return SOLID_RED_RGB8_PIXEL * (width * height)


def build_utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def build_frame_message_from_rgb8_payload(
    payload: bytes,
    *,
    width: int,
    height: int,
    frame_id: int = DEFAULT_TEST_FRAME_ID,
    timestamp: str | None = None,
    pixel_format: str = DEFAULT_TEST_FRAME_PIXEL_FORMAT,
) -> FrameMessage:
    if frame_id < 0:
        raise ValueError("frame_id must be non-negative")
    if pixel_format != DEFAULT_TEST_FRAME_PIXEL_FORMAT:
        raise ValueError(f"unsupported pixel format: {pixel_format}")

    resolved_timestamp = build_utc_timestamp() if timestamp is None else timestamp
    if not resolved_timestamp:
        raise ValueError("timestamp must not be empty")

    stride = build_rgb8_stride(width)
    expected_payload_size = stride * height
    if len(payload) != expected_payload_size:
        raise ValueError(
            f"payload size {len(payload)} does not match expected rgb8 frame size {expected_payload_size}"
        )

    metadata = FrameMetadata(
        frame_id=frame_id,
        timestamp=resolved_timestamp,
        width=width,
        height=height,
        stride=stride,
        pixel_format=pixel_format,
    )
    return FrameMessage(metadata=metadata, payload=bytes(payload))


def build_frame_message(
    frame_id: int = DEFAULT_TEST_FRAME_ID,
    timestamp: str = DEFAULT_TEST_FRAME_TIMESTAMP,
    width: int = DEFAULT_TEST_FRAME_WIDTH,
    height: int = DEFAULT_TEST_FRAME_HEIGHT,
    pixel_format: str = DEFAULT_TEST_FRAME_PIXEL_FORMAT,
) -> FrameMessage:
    payload = build_solid_red_payload(width=width, height=height, pixel_format=pixel_format)
    return build_frame_message_from_rgb8_payload(
        payload,
        width=width,
        height=height,
        frame_id=frame_id,
        timestamp=timestamp,
        pixel_format=pixel_format,
    )


def build_test_frame_message(
    frame_id: int = DEFAULT_TEST_FRAME_ID,
    timestamp: str = DEFAULT_TEST_FRAME_TIMESTAMP,
    width: int = DEFAULT_TEST_FRAME_WIDTH,
    height: int = DEFAULT_TEST_FRAME_HEIGHT,
    pixel_format: str = DEFAULT_TEST_FRAME_PIXEL_FORMAT,
) -> FrameMessage:
    return build_frame_message(
        frame_id=frame_id,
        timestamp=timestamp,
        width=width,
        height=height,
        pixel_format=pixel_format,
    )


class ZenohWorker:
    def __init__(
        self,
        state: RenderWorkerState,
        session: zenoh.Session,
        publisher: zenoh.Publisher,
        publish_interval_s: float,
        frame_metadata_publisher: zenoh.Publisher | None = None,
        frame_payload_publisher: zenoh.Publisher | None = None,
        camera_request_subscriber: zenoh.Subscriber | None = None,
        camera_offset: CameraOffsetState = CameraOffsetState(),
    ) -> None:
        self._state = state
        self._session = session
        self._publisher = publisher
        self._publish_interval_s = publish_interval_s
        self._frame_metadata_publisher = frame_metadata_publisher
        self._frame_payload_publisher = frame_payload_publisher
        self._camera_request_subscriber = camera_request_subscriber
        self._camera_offset = camera_offset
        self._camera_update_count = 0
        self._consumed_camera_update_count = 0
        self._lock = Lock()

    @classmethod
    def create(
        cls,
        key_expr: str | None = None,
        frame_metadata_key_expr: str | None = None,
        frame_payload_key_expr: str | None = None,
        config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH,
    ) -> "ZenohWorker":
        config = build_config(config_path)
        topic_key_exprs = load_topic_key_exprs(config_path)
        session = zenoh.open(config)
        publisher = session.declare_publisher(
            key_expr or topic_key_exprs.state,
            encoding=zenoh.Encoding.APPLICATION_JSON,
        )
        frame_metadata_publisher = session.declare_publisher(
            frame_metadata_key_expr or topic_key_exprs.frame_metadata,
            encoding=zenoh.Encoding.APPLICATION_JSON,
        )
        frame_payload_publisher = session.declare_publisher(
            frame_payload_key_expr or topic_key_exprs.frame_payload,
            encoding=zenoh.Encoding.APPLICATION_OCTET_STREAM,
        )
        worker = cls(
            state=RenderWorkerState(),
            session=session,
            publisher=publisher,
            publish_interval_s=load_publish_interval_s(config_path),
            frame_metadata_publisher=frame_metadata_publisher,
            frame_payload_publisher=frame_payload_publisher,
        )
        worker._camera_request_subscriber = session.declare_subscriber(
            topic_key_exprs.camera_request,
            worker._handle_camera_request,
        )
        return worker

    @property
    def state(self) -> RenderWorkerState:
        with self._lock:
            return self._state

    @property
    def publish_interval_s(self) -> float:
        return self._publish_interval_s

    @property
    def camera_offset(self) -> CameraOffsetState:
        with self._lock:
            return self._camera_offset

    def publish_current_state(self) -> None:
        with self._lock:
            self._publish_state_unlocked(self._state)

    def update_state(self, state: RenderWorkerState) -> None:
        with self._lock:
            if state == self._state:
                return

            self._state = state
            self._publish_state_unlocked(state)

    def apply_camera_offset(self, camera_offset: CameraOffsetState) -> None:
        with self._lock:
            if camera_offset == self._camera_offset:
                return

            self._camera_offset = camera_offset
            self._camera_update_count += 1

    def consume_camera_update(self) -> bool:
        with self._lock:
            if self._consumed_camera_update_count == self._camera_update_count:
                return False

            self._consumed_camera_update_count = self._camera_update_count
            return True

    def _handle_camera_request(self, sample: zenoh.Sample) -> None:
        try:
            camera_offset = parse_camera_offset_payload(sample.payload.to_string())
        except Exception as exc:
            print(f"Failed to parse camera request: {exc}", flush=True)
            return

        self.apply_camera_offset(camera_offset)
        print(
            f"Received camera request on {sample.key_expr}: "
            f"({camera_offset.offset_x:.3f}, {camera_offset.offset_y:.3f}, {camera_offset.offset_z:.3f})",
            flush=True,
        )

    def _publish_state_unlocked(self, state: RenderWorkerState) -> None:
        print(f"Publishing state: {state}")
        self._publisher.put(
            serialize_state(state),
            encoding=zenoh.Encoding.APPLICATION_JSON,
        )

    def publish_frame(self, frame: FrameMessage | None = None) -> None:
        if self._frame_metadata_publisher is None or self._frame_payload_publisher is None:
            raise RuntimeError("frame publishers are not configured")

        with self._lock:
            self._publish_frame_unlocked(frame)

    def _publish_frame_unlocked(self, frame: FrameMessage | None = None) -> None:
        print("Publishing frame...")
        if self._frame_metadata_publisher is None or self._frame_payload_publisher is None:
            raise RuntimeError("frame publishers are not configured")

        frame_message = frame if frame is not None else build_frame_message()
        print(f"Publishing frame metadata: {frame_message.metadata}")
        self._frame_metadata_publisher.put(
            serialize_frame_metadata(frame_message.metadata),
            encoding=zenoh.Encoding.APPLICATION_JSON,
        )
        self._frame_payload_publisher.put(
            frame_message.payload,
            encoding=zenoh.Encoding.APPLICATION_OCTET_STREAM,
        )

    def publish_test_frame(self, frame: FrameMessage | None = None) -> None:
        self.publish_frame(frame)

    def close(self) -> None:
        for publisher in (
            self._publisher,
            self._frame_metadata_publisher,
            self._frame_payload_publisher,
            self._camera_request_subscriber,
        ):
            undeclare_publisher = getattr(publisher, "undeclare", None)
            if callable(undeclare_publisher):
                undeclare_publisher()

        close_session = getattr(self._session, "close", None)
        if callable(close_session):
            close_session()
