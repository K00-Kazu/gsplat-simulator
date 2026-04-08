from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import zenoh


DEFAULT_STATE_KEY_EXPR = "simulation/render/response/state"
DEFAULT_TRANSPORT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "transport.dev.json"
)


class RenderLifecycleState(str, Enum):
    IDLE = "Idle"


@dataclass(frozen=True)
class RenderWorkerState:
    lifecycle: RenderLifecycleState = RenderLifecycleState.IDLE


def serialize_state(state: RenderWorkerState) -> str:
    return json.dumps({"state": state.lifecycle.value}, separators=(",", ":"))


def build_config(config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH) -> zenoh.Config:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    zenoh_section = raw["zenoh"]
    return zenoh.Config.from_json5(json.dumps(zenoh_section))
    #return zenoh.Config.from_file(str(config_path))

def load_publish_interval_s(config_path: Path) -> float:
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    publish_interval_ms = raw["timeouts"]["publish_interval_ms"]
    return float(publish_interval_ms) / 1000.0


class ZenohWorker:
    def __init__(
        self,
        state: RenderWorkerState,
        session: zenoh.Session,
        publisher: zenoh.Publisher,
        publish_interval_s: float,
    ) -> None:
        self._state = state
        self._session = session
        self._publisher = publisher
        self._publish_interval_s = publish_interval_s

    @classmethod
    def create(
        cls,
        key_expr: str = DEFAULT_STATE_KEY_EXPR,
        config_path: Path = DEFAULT_TRANSPORT_CONFIG_PATH,
    ) -> "ZenohWorker":
        config = build_config(config_path)
        session = zenoh.open(config)
        publisher = session.declare_publisher(
            key_expr,
            encoding=zenoh.Encoding.APPLICATION_JSON,
        )
        return cls(
            state=RenderWorkerState(),
            session=session,
            publisher=publisher,
            publish_interval_s=load_publish_interval_s(config_path),
        )

    @property
    def state(self) -> RenderWorkerState:
        return self._state

    @property
    def publish_interval_s(self) -> float:
        return self._publish_interval_s

    def publish_current_state(self) -> None:
        print(f"Publishing state: {self._state}")
        self._publisher.put(
            serialize_state(self._state),
            encoding=zenoh.Encoding.APPLICATION_JSON,
        )

    def close(self) -> None:
        undeclare_publisher = getattr(self._publisher, "undeclare", None)
        if callable(undeclare_publisher):
            undeclare_publisher()

        close_session = getattr(self._session, "close", None)
        if callable(close_session):
            close_session()
