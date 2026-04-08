from __future__ import annotations

import argparse
import json
from typing import Any

import zenoh

DEFAULT_KEY_EXPR = "simulation/core/gaze_vector"
DEFAULT_LISTEN_ENDPOINT = "tcp/127.0.0.1:7447"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Zenoh で送られてきた視線ベクトルを表示します。"
    )
    parser.add_argument(
        "--key-expr",
        default=DEFAULT_KEY_EXPR,
        help=f"subscribe する topic。default: {DEFAULT_KEY_EXPR}",
    )
    parser.add_argument(
        "--listen-endpoint",
        default=DEFAULT_LISTEN_ENDPOINT,
        help=f"listen する endpoint。default: {DEFAULT_LISTEN_ENDPOINT}",
    )
    parser.add_argument(
        "--max-messages",
        type=int,
        default=None,
        help="受信後に終了する最大メッセージ数。未指定なら継続。",
    )
    return parser.parse_args()


def format_sample(sample: Any) -> str:
    payload_text = sample.payload.to_string()

    try:
        parsed = json.loads(payload_text)
    except json.JSONDecodeError:
        return f"[{sample.key_expr}] raw={payload_text}"

    vector = parsed.get("vector")
    sequence = parsed.get("sequence")
    return f"[{sample.key_expr}] sequence={sequence} vector={vector}"


def build_config(listen_endpoint: str) -> zenoh.Config:
    config = zenoh.Config()
    config.insert_json5("scouting/multicast/enabled", "false")
    config.insert_json5("listen/endpoints", json.dumps([listen_endpoint]))
    return config


def main() -> None:
    args = parse_args()

    session = zenoh.open(build_config(args.listen_endpoint))
    subscriber = session.declare_subscriber(args.key_expr)

    print(
        f"Subscribed to `{args.key_expr}` on `{args.listen_endpoint}`. Ctrl+C で終了します。",
        flush=True,
    )

    received = 0

    try:
        while True:
            sample = subscriber.recv()
            received += 1
            print(format_sample(sample), flush=True)

            if args.max_messages is not None and received >= args.max_messages:
                break
    except KeyboardInterrupt:
        print("Stopping subscriber.")
    finally:
        subscriber.undeclare()

        close_session = getattr(session, "close", None)
        if callable(close_session):
            close_session()


if __name__ == "__main__":
    main()
