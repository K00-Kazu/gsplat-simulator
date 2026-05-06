from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, replace
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Callable, Sequence

import numpy as np
import torch
from plyfile import PlyData


SH_C0 = 0.28209479177387814
DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GAUSSIAN_SPLAT_PLY_PATH = DEFAULT_REPO_ROOT / "assets" / "sample_point_cloud.ply"
DEFAULT_RENDER_CONFIG_PATH = DEFAULT_REPO_ROOT / "config" / "render.dev.json"
DEFAULT_RENDER_PREVIEW_OUTPUT_PATH = DEFAULT_REPO_ROOT / "runtime" / "cache" / "render_worker_preview.png"
DEFAULT_RENDER_PREVIEW_WIDTH = 1280
DEFAULT_RENDER_PREVIEW_HEIGHT = 720
DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH = 900.0
DEFAULT_RENDER_PREVIEW_CAMERA_DISTANCE_SCALE = 2.5
DEFAULT_RENDER_PREVIEW_CAMERA_HEIGHT_SCALE = 0.8
DEFAULT_RENDER_PREVIEW_MAX_PITCH_DEGREES = 80.0
DEFAULT_RENDER_PREVIEW_MIN_FOCAL_LENGTH = 100.0
DEFAULT_ROBOT_BODY_SIZE_M = (0.6, 0.4, 0.3)
DEFAULT_ROBOT_BODY_COLOR_RGBA = (0.18, 0.64, 0.87, 0.9)
DEFAULT_ROBOT_POSITION_M = (0.0, 0.0, 0.15)
DEFAULT_ROBOT_YAW_PITCH_ROLL_DEG = (0.0, 0.0, 0.0)


class RenderLifecycleState(str, Enum):
    IDLE = "Idle"
    LOADING = "Loading"
    RENDERING = "Rendering"
    COMPLETED = "Completed"
    ERROR = "Error"


@dataclass(frozen=True)
class RenderWorkerState:
    lifecycle: RenderLifecycleState = RenderLifecycleState.IDLE


@dataclass(frozen=True)
class GaussianSplatModel:
    ply_path: Path
    means: torch.Tensor
    quats: torch.Tensor
    scales: torch.Tensor
    opacities: torch.Tensor
    colors: torch.Tensor
    sh_degree: int | None = None

    @property
    def point_count(self) -> int:
        return int(self.means.shape[0])


@dataclass(frozen=True)
class RenderedPreviewFrame:
    width: int
    height: int
    payload: bytes


@dataclass(frozen=True)
class PreviewCameraState:
    frame_id: int = -1
    timestamp: str = ""
    camera_role: str = "preview"
    eye: tuple[float, float, float] = (0.0, 0.0, 0.0)
    target: tuple[float, float, float] = (0.0, 0.0, 0.0)
    up: tuple[float, float, float] = (0.0, 0.0, 1.0)
    scene_center: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scene_radius: float = 0.0
    focal_length_px: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH
    image_width: int = DEFAULT_RENDER_PREVIEW_WIDTH
    image_height: int = DEFAULT_RENDER_PREVIEW_HEIGHT
    world_up_axis: str = "z"
    gizmo_enabled: bool = True


@dataclass(frozen=True)
class PreviewRenderResult:
    frame: RenderedPreviewFrame
    camera_state: PreviewCameraState


@dataclass(frozen=True)
class PreviewRenderConfig:
    ply_path: Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH
    focal_length_px: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH


@dataclass(frozen=True)
class PreviewCameraControlState:
    pan_x: float = 0.0
    pan_y: float = 0.0
    pan_z: float = 0.0
    yaw_degrees: float = 0.0
    pitch_degrees: float = 0.0


@dataclass(frozen=True)
class RobotPoseState:
    position_m: tuple[float, float, float] = DEFAULT_ROBOT_POSITION_M
    yaw_pitch_roll_deg: tuple[float, float, float] = DEFAULT_ROBOT_YAW_PITCH_ROLL_DEG


@dataclass(frozen=True)
class RobotBodyState:
    size_m: tuple[float, float, float] = DEFAULT_ROBOT_BODY_SIZE_M
    color_rgba: tuple[float, float, float, float] = DEFAULT_ROBOT_BODY_COLOR_RGBA


@dataclass(frozen=True)
class RobotState:
    id: str = "robot_01"
    enabled: bool = True
    pose: RobotPoseState = RobotPoseState()
    body: RobotBodyState = RobotBodyState()


CameraOffsetState = PreviewCameraControlState


StateChangeCallback = Callable[[RenderWorkerState], None]
RenderInitializationStep = Callable[[], None]
RenderFrameOutput = RenderedPreviewFrame | PreviewRenderResult
RenderFrameStep = Callable[[], RenderFrameOutput]
FramePublishCallback = Callable[[RenderFrameOutput], None]
CameraUpdateCallback = Callable[[], bool]


def build_render_worker_state(lifecycle: RenderLifecycleState) -> RenderWorkerState:
    return RenderWorkerState(lifecycle=lifecycle)


def build_gaussian_splat_path(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
) -> Path:
    resolved_path = Path(ply_path)
    if not resolved_path.is_file():
        raise FileNotFoundError(f"gaussian splatting ply file was not found: {resolved_path}")
    return resolved_path


def resolve_repo_path(path_value: str | Path, repo_root: Path = DEFAULT_REPO_ROOT) -> Path:
    candidate = Path(path_value)
    if candidate.is_absolute():
        return candidate
    return repo_root / candidate


def validate_preview_focal_length(focal_length_px: float) -> float:
    if not math.isfinite(focal_length_px):
        raise ValueError("preview focal length must be finite")
    if focal_length_px < DEFAULT_RENDER_PREVIEW_MIN_FOCAL_LENGTH:
        raise ValueError(
            f"preview focal length must be at least {DEFAULT_RENDER_PREVIEW_MIN_FOCAL_LENGTH}"
        )
    return float(focal_length_px)


def require_float_sequence(
    value: object,
    path: str,
    *,
    length: int,
) -> tuple[float, ...]:
    if not isinstance(value, list) or len(value) != length:
        raise ValueError(f"{path} must be an array with {length} numeric values")

    resolved: list[float] = []
    for index, item in enumerate(value):
        if not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise ValueError(f"{path}[{index}] must be finite")
        resolved.append(float(item))

    return tuple(resolved)


def normalize_angle_degrees(angle_degrees: float) -> float:
    return ((float(angle_degrees) + 180.0) % 360.0) - 180.0


def validate_robot_pose_state(robot_pose: RobotPoseState) -> RobotPoseState:
    position = tuple(float(value) for value in robot_pose.position_m)
    rotation = tuple(float(value) for value in robot_pose.yaw_pitch_roll_deg)
    if len(position) != 3 or not all(math.isfinite(value) for value in position):
        raise ValueError("robot position must contain three finite values")
    if len(rotation) != 3 or not all(math.isfinite(value) for value in rotation):
        raise ValueError("robot rotation must contain three finite values")

    return RobotPoseState(
        position_m=position,
        yaw_pitch_roll_deg=tuple(normalize_angle_degrees(value) for value in rotation),
    )


def validate_robot_body_state(robot_body: RobotBodyState) -> RobotBodyState:
    size_m = tuple(float(value) for value in robot_body.size_m)
    color_rgba = tuple(float(value) for value in robot_body.color_rgba)
    if len(size_m) != 3 or not all(math.isfinite(value) and value > 0.0 for value in size_m):
        raise ValueError("robot size must contain three positive finite values")
    if len(color_rgba) != 4 or not all(math.isfinite(value) for value in color_rgba):
        raise ValueError("robot color must contain four finite values")

    return RobotBodyState(
        size_m=size_m,
        color_rgba=tuple(max(0.0, min(1.0, value)) for value in color_rgba),
    )


def validate_robot_state(robot_state: RobotState) -> RobotState:
    if not robot_state.id.strip():
        raise ValueError("robot id must not be empty")

    return RobotState(
        id=robot_state.id.strip(),
        enabled=bool(robot_state.enabled),
        pose=validate_robot_pose_state(robot_state.pose),
        body=validate_robot_body_state(robot_state.body),
    )


def load_robot_states(
    config_path: Path = DEFAULT_RENDER_CONFIG_PATH,
) -> tuple[RobotState, ...]:
    resolved_config_path = Path(config_path)
    if not resolved_config_path.is_file():
        return ()

    raw = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("render config must be a JSON object")

    raw_robots = raw.get("robots", [])
    if raw_robots is None:
        return ()
    if not isinstance(raw_robots, list):
        raise ValueError("render config `robots` must be an array")

    robot_states: list[RobotState] = []
    for index, raw_robot in enumerate(raw_robots):
        if not isinstance(raw_robot, dict):
            raise ValueError(f"render config `robots[{index}]` must be an object")

        enabled = bool(raw_robot.get("enabled", True))
        robot_id = raw_robot.get("id", f"robot_{index + 1:02d}")
        if not isinstance(robot_id, str) or not robot_id.strip():
            raise ValueError(f"render config `robots[{index}].id` must be a non-empty string")

        raw_body = raw_robot.get("body", {})
        if not isinstance(raw_body, dict):
            raise ValueError(f"render config `robots[{index}].body` must be an object")
        shape = raw_body.get("shape", "box")
        if shape != "box":
            raise ValueError(f"render config `robots[{index}].body.shape` must be `box`")

        raw_initial_pose = raw_robot.get("initial_pose", {})
        if not isinstance(raw_initial_pose, dict):
            raise ValueError(f"render config `robots[{index}].initial_pose` must be an object")

        robot_states.append(
            validate_robot_state(
                RobotState(
                    id=robot_id,
                    enabled=enabled,
                    pose=RobotPoseState(
                        position_m=require_float_sequence(
                            raw_initial_pose.get("position_m", list(DEFAULT_ROBOT_POSITION_M)),
                            f"robots[{index}].initial_pose.position_m",
                            length=3,
                        ),
                        yaw_pitch_roll_deg=require_float_sequence(
                            raw_initial_pose.get(
                                "yaw_pitch_roll_deg",
                                list(DEFAULT_ROBOT_YAW_PITCH_ROLL_DEG),
                            ),
                            f"robots[{index}].initial_pose.yaw_pitch_roll_deg",
                            length=3,
                        ),
                    ),
                    body=RobotBodyState(
                        size_m=require_float_sequence(
                            raw_body.get("size_m", list(DEFAULT_ROBOT_BODY_SIZE_M)),
                            f"robots[{index}].body.size_m",
                            length=3,
                        ),
                        color_rgba=require_float_sequence(
                            raw_body.get("color_rgba", list(DEFAULT_ROBOT_BODY_COLOR_RGBA)),
                            f"robots[{index}].body.color_rgba",
                            length=4,
                        ),
                    ),
                )
            )
        )

    return tuple(robot_states)


def normalize_preview_render_config(
    config: PreviewRenderConfig,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> PreviewRenderConfig:
    return PreviewRenderConfig(
        ply_path=build_gaussian_splat_path(resolve_repo_path(config.ply_path, repo_root)),
        focal_length_px=validate_preview_focal_length(config.focal_length_px),
    )


def build_preview_render_config_json(
    config: PreviewRenderConfig,
    repo_root: Path = DEFAULT_REPO_ROOT,
    existing_root: dict[str, object] | None = None,
) -> str:
    normalized_config = normalize_preview_render_config(config, repo_root)
    try:
        serialized_ply_path = normalized_config.ply_path.relative_to(repo_root).as_posix()
    except ValueError:
        serialized_ply_path = normalized_config.ply_path.as_posix()

    root: dict[str, object] = {} if existing_root is None else dict(existing_root)
    preview_root = root.get("preview", {})
    if not isinstance(preview_root, dict):
        preview_root = {}

    merged_preview_root = dict(preview_root)
    merged_preview_root.update(
        {
            "ply_path": serialized_ply_path,
            "focal_length_px": normalized_config.focal_length_px,
        }
    )
    root["preview"] = merged_preview_root

    return json.dumps(
        root,
        indent=2,
    ) + "\n"


def load_preview_render_config(
    config_path: Path = DEFAULT_RENDER_CONFIG_PATH,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> PreviewRenderConfig:
    resolved_config_path = Path(config_path)
    if not resolved_config_path.is_file():
        return normalize_preview_render_config(PreviewRenderConfig(), repo_root)

    raw = json.loads(resolved_config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("render config must be a JSON object")

    preview = raw.get("preview", {})
    if not isinstance(preview, dict):
        raise ValueError("render config `preview` must be a JSON object")

    ply_path_value = preview.get("ply_path", DEFAULT_GAUSSIAN_SPLAT_PLY_PATH.as_posix())
    if not isinstance(ply_path_value, str) or not ply_path_value.strip():
        raise ValueError("render config `preview.ply_path` must be a non-empty string")

    focal_length_value = preview.get("focal_length_px", DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH)
    if not isinstance(focal_length_value, (int, float)):
        raise ValueError("render config `preview.focal_length_px` must be numeric")

    return normalize_preview_render_config(
        PreviewRenderConfig(
            ply_path=resolve_repo_path(ply_path_value.strip(), repo_root),
            focal_length_px=float(focal_length_value),
        ),
        repo_root,
    )


def save_preview_render_config(
    config: PreviewRenderConfig,
    config_path: Path = DEFAULT_RENDER_CONFIG_PATH,
    repo_root: Path = DEFAULT_REPO_ROOT,
) -> None:
    resolved_config_path = Path(config_path)
    resolved_config_path.parent.mkdir(parents=True, exist_ok=True)
    existing_root: dict[str, object] | None = None
    if resolved_config_path.is_file():
        raw = json.loads(resolved_config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("render config must be a JSON object")
        existing_root = raw
    resolved_config_path.write_text(
        build_preview_render_config_json(config, repo_root, existing_root),
        encoding="utf-8",
    )


def validate_max_vertices(max_vertices: int | None) -> None:
    if max_vertices is not None and max_vertices < 1:
        raise ValueError("max_vertices must be positive")


def validate_image_size(width: int, height: int) -> None:
    if width < 1:
        raise ValueError("width must be positive")
    if height < 1:
        raise ValueError("height must be positive")


def build_rendered_preview_frame(rgb8_image: np.ndarray) -> RenderedPreviewFrame:
    if rgb8_image.ndim != 3 or rgb8_image.shape[2] != 3:
        raise ValueError("rgb8_image must have shape [height, width, 3]")

    height, width, _channels = rgb8_image.shape
    validate_image_size(width, height)
    contiguous_rgb8_image = np.ascontiguousarray(rgb8_image, dtype=np.uint8)
    return RenderedPreviewFrame(
        width=width,
        height=height,
        payload=contiguous_rgb8_image.tobytes(),
    )


def validate_camera_offset_state(camera_offset: CameraOffsetState) -> CameraOffsetState:
    values = (
        camera_offset.pan_x,
        camera_offset.pan_y,
        camera_offset.pan_z,
        camera_offset.yaw_degrees,
        camera_offset.pitch_degrees,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("preview camera controls must be finite numbers")

    return replace(
        camera_offset,
        yaw_degrees=((camera_offset.yaw_degrees + 180.0) % 360.0) - 180.0,
        pitch_degrees=max(
            -DEFAULT_RENDER_PREVIEW_MAX_PITCH_DEGREES,
            min(DEFAULT_RENDER_PREVIEW_MAX_PITCH_DEGREES, camera_offset.pitch_degrees),
        ),
    )


def tensor_to_float3(vector: torch.Tensor) -> tuple[float, float, float]:
    return tuple(float(value) for value in vector.detach().cpu().tolist())


def safe_normalize_tensor(vector: torch.Tensor, fallback: Sequence[float], *, device: str) -> torch.Tensor:
    if float(torch.linalg.norm(vector).item()) <= 1e-6:
        return torch.tensor(fallback, dtype=torch.float32, device=device)

    return vector / torch.linalg.norm(vector)


def build_axis_angle_rotation_matrix(
    axis: torch.Tensor,
    angle_radians: float,
    *,
    device: str,
) -> torch.Tensor:
    normalized_axis = safe_normalize_tensor(axis, (0.0, 0.0, 1.0), device=device)
    axis_x, axis_y, axis_z = [float(value) for value in normalized_axis.detach().cpu().tolist()]
    cos_theta = math.cos(angle_radians)
    sin_theta = math.sin(angle_radians)
    one_minus_cos = 1.0 - cos_theta

    return torch.tensor(
        [
            [
                cos_theta + axis_x * axis_x * one_minus_cos,
                axis_x * axis_y * one_minus_cos - axis_z * sin_theta,
                axis_x * axis_z * one_minus_cos + axis_y * sin_theta,
            ],
            [
                axis_y * axis_x * one_minus_cos + axis_z * sin_theta,
                cos_theta + axis_y * axis_y * one_minus_cos,
                axis_y * axis_z * one_minus_cos - axis_x * sin_theta,
            ],
            [
                axis_z * axis_x * one_minus_cos - axis_y * sin_theta,
                axis_z * axis_y * one_minus_cos + axis_x * sin_theta,
                cos_theta + axis_z * axis_z * one_minus_cos,
            ],
        ],
        dtype=torch.float32,
        device=device,
    )


def build_preview_camera_pose(
    means: torch.Tensor,
    *,
    device: str,
    camera_offset: CameraOffsetState = CameraOffsetState(),
) -> tuple[torch.Tensor, torch.Tensor, float, torch.Tensor, torch.Tensor]:
    resolved_camera_offset = validate_camera_offset_state(camera_offset)
    center = means.mean(dim=0)
    distances = torch.linalg.norm(means - center, dim=1)
    radius = max(float(torch.quantile(distances, 0.95).item()), 1e-3)
    world_up = torch.tensor([0.0, 0.0, 1.0], dtype=torch.float32, device=device)
    target = center + torch.tensor(
        [
            resolved_camera_offset.pan_x * radius,
            resolved_camera_offset.pan_y * radius,
            resolved_camera_offset.pan_z * radius,
        ],
        dtype=torch.float32,
        device=device,
    )
    default_eye_offset = torch.tensor(
        [
            0.0,
            -DEFAULT_RENDER_PREVIEW_CAMERA_DISTANCE_SCALE * radius,
            DEFAULT_RENDER_PREVIEW_CAMERA_HEIGHT_SCALE * radius,
        ],
        dtype=torch.float32,
        device=device,
    )

    yaw_rotation = build_axis_angle_rotation_matrix(
        world_up,
        math.radians(resolved_camera_offset.yaw_degrees),
        device=device,
    )
    yawed_eye_offset = yaw_rotation @ default_eye_offset
    yawed_up = safe_normalize_tensor(yaw_rotation @ world_up, (0.0, 0.0, 1.0), device=device)

    forward = safe_normalize_tensor(-yawed_eye_offset, (0.0, 1.0, 0.0), device=device)
    right = safe_normalize_tensor(
        torch.cross(forward, yawed_up, dim=0),
        (1.0, 0.0, 0.0),
        device=device,
    )
    pitch_rotation = build_axis_angle_rotation_matrix(
        right,
        math.radians(-resolved_camera_offset.pitch_degrees),
        device=device,
    )
    rotated_eye_offset = pitch_rotation @ yawed_eye_offset
    rotated_up = safe_normalize_tensor(
        pitch_rotation @ yawed_up,
        (0.0, 0.0, 1.0),
        device=device,
    )

    eye = target + rotated_eye_offset
    return center, target, radius, eye, rotated_up


def build_preview_camera_state(
    means: torch.Tensor,
    *,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    device: str,
    camera_offset: CameraOffsetState = CameraOffsetState(),
) -> PreviewCameraState:
    validate_image_size(width, height)
    center, target, radius, eye, up = build_preview_camera_pose(
        means,
        device=device,
        camera_offset=camera_offset,
    )
    return PreviewCameraState(
        eye=tensor_to_float3(eye),
        target=tensor_to_float3(target),
        up=tensor_to_float3(up),
        scene_center=tensor_to_float3(center),
        scene_radius=radius,
        focal_length_px=float(focal_length),
        image_width=width,
        image_height=height,
        world_up_axis="z",
        gizmo_enabled=True,
    )


def build_robot_rotation_matrix(yaw_pitch_roll_deg: Sequence[float]) -> np.ndarray:
    yaw_radians, pitch_radians, roll_radians = [
        math.radians(float(value)) for value in yaw_pitch_roll_deg
    ]
    yaw_rotation = np.array(
        [
            [math.cos(yaw_radians), -math.sin(yaw_radians), 0.0],
            [math.sin(yaw_radians), math.cos(yaw_radians), 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float32,
    )
    pitch_rotation = np.array(
        [
            [math.cos(pitch_radians), 0.0, math.sin(pitch_radians)],
            [0.0, 1.0, 0.0],
            [-math.sin(pitch_radians), 0.0, math.cos(pitch_radians)],
        ],
        dtype=np.float32,
    )
    roll_rotation = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(roll_radians), -math.sin(roll_radians)],
            [0.0, math.sin(roll_radians), math.cos(roll_radians)],
        ],
        dtype=np.float32,
    )
    return yaw_rotation @ pitch_rotation @ roll_rotation


def build_robot_box_vertices(robot_state: RobotState) -> np.ndarray:
    validated_state = validate_robot_state(robot_state)
    size_x, size_y, size_z = validated_state.body.size_m
    half_extents = np.array(
        [size_x * 0.5, size_y * 0.5, size_z * 0.5],
        dtype=np.float32,
    )
    local_vertices = np.array(
        [
            [-half_extents[0], -half_extents[1], -half_extents[2]],
            [half_extents[0], -half_extents[1], -half_extents[2]],
            [half_extents[0], half_extents[1], -half_extents[2]],
            [-half_extents[0], half_extents[1], -half_extents[2]],
            [-half_extents[0], -half_extents[1], half_extents[2]],
            [half_extents[0], -half_extents[1], half_extents[2]],
            [half_extents[0], half_extents[1], half_extents[2]],
            [-half_extents[0], half_extents[1], half_extents[2]],
        ],
        dtype=np.float32,
    )
    rotation = build_robot_rotation_matrix(validated_state.pose.yaw_pitch_roll_deg)
    center = np.array(validated_state.pose.position_m, dtype=np.float32)
    return (rotation @ local_vertices.T).T + center


def project_world_points_to_preview_image(
    world_points: np.ndarray,
    *,
    preview_camera_state: PreviewCameraState,
) -> tuple[np.ndarray, np.ndarray]:
    if world_points.ndim != 2 or world_points.shape[1] != 3:
        raise ValueError("world_points must have shape [count, 3]")

    view_matrix = build_look_at_view_matrix(
        preview_camera_state.eye,
        preview_camera_state.target,
        up=preview_camera_state.up,
        device="cpu",
    ).detach().cpu().numpy()
    homogeneous_world_points = np.concatenate(
        [
            world_points.astype(np.float32, copy=False),
            np.ones((world_points.shape[0], 1), dtype=np.float32),
        ],
        axis=1,
    )
    camera_points = (view_matrix @ homogeneous_world_points.T).T[:, :3]
    depth = camera_points[:, 2]
    pixel_points = np.full((world_points.shape[0], 2), np.nan, dtype=np.float32)
    visible = depth > 1e-4
    if np.any(visible):
        fx = float(preview_camera_state.focal_length_px)
        fy = float(preview_camera_state.focal_length_px)
        cx = preview_camera_state.image_width * 0.5
        cy = preview_camera_state.image_height * 0.5
        pixel_points[visible, 0] = fx * (camera_points[visible, 0] / depth[visible]) + cx
        pixel_points[visible, 1] = cy - fy * (camera_points[visible, 1] / depth[visible])

    return pixel_points, depth


def overlay_robot_states_on_preview_frame(
    rgb8_image: np.ndarray,
    *,
    preview_camera_state: PreviewCameraState,
    robot_states: Sequence[RobotState],
) -> np.ndarray:
    from PIL import Image, ImageDraw

    validate_image_size(preview_camera_state.image_width, preview_camera_state.image_height)
    if rgb8_image.ndim != 3 or rgb8_image.shape[2] != 3:
        raise ValueError("rgb8_image must have shape [height, width, 3]")

    composited_source = np.ascontiguousarray(rgb8_image, dtype=np.uint8)
    image_height, image_width, _ = composited_source.shape
    if (
        image_width != preview_camera_state.image_width
        or image_height != preview_camera_state.image_height
    ):
        raise ValueError("preview image size must match the preview camera state image size")

    base_image = Image.fromarray(composited_source, mode="RGB").convert("RGBA")
    overlay_image = Image.new("RGBA", base_image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay_image, "RGBA")

    faces = (
        (0, 1, 2, 3),
        (4, 5, 6, 7),
        (0, 1, 5, 4),
        (1, 2, 6, 5),
        (2, 3, 7, 6),
        (3, 0, 4, 7),
    )
    edges = (
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 0),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 4),
        (0, 4),
        (1, 5),
        (2, 6),
        (3, 7),
    )

    for robot_state in robot_states:
        if not robot_state.enabled:
            continue

        vertices = build_robot_box_vertices(robot_state)
        projected_vertices, depth = project_world_points_to_preview_image(
            vertices,
            preview_camera_state=preview_camera_state,
        )
        if not np.any(np.isfinite(projected_vertices)):
            continue

        red, green, blue, alpha = validate_robot_body_state(robot_state.body).color_rgba
        outline_color = (
            int(round(red * 255.0)),
            int(round(green * 255.0)),
            int(round(blue * 255.0)),
            int(round(alpha * 255.0)),
        )
        fill_color = (
            outline_color[0],
            outline_color[1],
            outline_color[2],
            max(24, int(round(outline_color[3] * 0.25))),
        )

        sorted_faces = sorted(
            faces,
            key=lambda face_indices: float(np.nanmean(depth[list(face_indices)])),
            reverse=True,
        )
        for face in sorted_faces:
            face_points = [projected_vertices[index] for index in face]
            if not all(np.isfinite(point).all() for point in face_points):
                continue
            draw.polygon(
                [(float(point[0]), float(point[1])) for point in face_points],
                fill=fill_color,
            )

        for start_index, end_index in edges:
            start_point = projected_vertices[start_index]
            end_point = projected_vertices[end_index]
            if not np.isfinite(start_point).all() or not np.isfinite(end_point).all():
                continue
            draw.line(
                [
                    (float(start_point[0]), float(start_point[1])),
                    (float(end_point[0]), float(end_point[1])),
                ],
                fill=outline_color,
                width=3,
            )

        center_point, center_depth = project_world_points_to_preview_image(
            np.array([robot_state.pose.position_m], dtype=np.float32),
            preview_camera_state=preview_camera_state,
        )
        if np.isfinite(center_point[0]).all() and center_depth[0] > 1e-4:
            center_x = float(center_point[0, 0])
            center_y = float(center_point[0, 1])
            draw.ellipse(
                (center_x - 4.0, center_y - 4.0, center_x + 4.0, center_y + 4.0),
                fill=outline_color,
            )

    composited_image = Image.alpha_composite(base_image, overlay_image).convert("RGB")
    return np.array(composited_image, dtype=np.uint8)


def load_gaussian_splat_model(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str = "cpu",
    max_vertices: int | None = None,
) -> GaussianSplatModel:
    resolved_path = build_gaussian_splat_path(ply_path)
    validate_max_vertices(max_vertices)

    ply = PlyData.read(resolved_path, mmap="r")
    vertex = ply["vertex"]
    vertex_data = vertex.data if max_vertices is None else vertex.data[:max_vertices]
    names = set(vertex_data.dtype.names or ())

    required_fields = {
        "x",
        "y",
        "z",
        "scale_0",
        "scale_1",
        "scale_2",
        "rot_0",
        "rot_1",
        "rot_2",
        "rot_3",
        "opacity",
    }
    missing_fields = sorted(required_fields - names)
    if missing_fields:
        raise ValueError(
            "gaussian splatting ply is missing required vertex fields: "
            + ", ".join(missing_fields)
        )

    def column(name: str) -> np.ndarray:
        return np.array(vertex_data[name], dtype=np.float32, copy=True)

    def numbered_fields(prefix: str) -> list[str]:
        def field_index(name: str) -> int:
            return int(name.rsplit("_", 1)[1])

        fields = sorted(
            (name for name in names if name.startswith(prefix)),
            key=field_index,
        )
        expected_indices = list(range(len(fields)))
        actual_indices = [field_index(name) for name in fields]
        if actual_indices != expected_indices:
            raise ValueError(f"gaussian splatting ply `{prefix}*` fields must be contiguous")
        return fields

    def infer_sh_degree(rest_field_count: int) -> int:
        if rest_field_count % 3 != 0:
            raise ValueError("gaussian splatting ply `f_rest_*` field count must be divisible by 3")

        coefficient_count = (rest_field_count // 3) + 1
        sh_order = math.isqrt(coefficient_count)
        if sh_order * sh_order != coefficient_count:
            raise ValueError("gaussian splatting ply `f_rest_*` fields must form complete SH bands")
        return sh_order - 1

    means = np.stack([column("x"), column("y"), column("z")], axis=1)
    scales = np.stack([column("scale_0"), column("scale_1"), column("scale_2")], axis=1)
    quats = np.stack([column("rot_0"), column("rot_1"), column("rot_2"), column("rot_3")], axis=1)
    opacities = column("opacity")

    sh_color_fields = {"f_dc_0", "f_dc_1", "f_dc_2"}
    rgb_color_fields = {"red", "green", "blue"}
    sh_degree: int | None = None
    if sh_color_fields.issubset(names):
        sh_dc = np.stack([column("f_dc_0"), column("f_dc_1"), column("f_dc_2")], axis=1)
        rest_fields = numbered_fields("f_rest_")
        if rest_fields:
            sh_degree = infer_sh_degree(len(rest_fields))
            rest_coefficients = np.stack([column(name) for name in rest_fields], axis=1)
            rest_coefficients = rest_coefficients.reshape(
                rest_coefficients.shape[0],
                3,
                -1,
            ).transpose(0, 2, 1)
            colors = np.concatenate([sh_dc[:, None, :], rest_coefficients], axis=1)
        else:
            colors = sh_dc * SH_C0 + 0.5
    elif rgb_color_fields.issubset(names):
        colors = np.stack([column("red"), column("green"), column("blue")], axis=1) / 255.0
    else:
        raise ValueError(
            "gaussian splatting ply must contain color fields `f_dc_0..2` or `red/green/blue`"
        )

    means_tensor = torch.tensor(means, dtype=torch.float32, device=device)
    scales_tensor = torch.tensor(scales, dtype=torch.float32, device=device)
    quats_tensor = torch.tensor(quats, dtype=torch.float32, device=device)
    opacities_tensor = torch.tensor(opacities, dtype=torch.float32, device=device)
    colors_tensor = torch.tensor(colors, dtype=torch.float32, device=device)

    return GaussianSplatModel(
        ply_path=resolved_path,
        means=means_tensor,
        quats=torch.nn.functional.normalize(quats_tensor, dim=-1),
        scales=torch.exp(scales_tensor),
        opacities=torch.sigmoid(opacities_tensor),
        colors=colors_tensor,
        sh_degree=sh_degree,
    )


def require_gsplat_rasterization() -> Callable[..., tuple[torch.Tensor, torch.Tensor, dict[str, object]]]:
    patch_torch_cpp_extension_for_windows()
    try:
        from gsplat.rendering import rasterization
    except ImportError as exc:
        raise RuntimeError(
            "gsplat is not installed in the active Python environment. "
            "Activate apps/render/.venv or install gsplat before running render_worker.py."
        ) from exc

    return rasterization


def patch_torch_cpp_extension_for_windows() -> None:
    if os.name != "nt":
        return

    from torch.utils import cpp_extension

    original_jit_compile = cpp_extension._jit_compile
    if getattr(original_jit_compile, "_gsplat_windows_flag_patch", False):
        return

    def patched_jit_compile(*args, **kwargs):
        updated_args = list(args)
        if len(updated_args) > 2 and updated_args[2] is not None:
            updated_args[2] = [
                flag for flag in updated_args[2] if flag != "-Wno-attributes"
            ]
        if kwargs.get("extra_cflags") is not None:
            kwargs["extra_cflags"] = [
                flag for flag in kwargs["extra_cflags"] if flag != "-Wno-attributes"
            ]
        return original_jit_compile(*updated_args, **kwargs)

    patched_jit_compile._gsplat_windows_flag_patch = True  # type: ignore[attr-defined]
    cpp_extension._jit_compile = patched_jit_compile


def restart_in_utf8_mode_if_needed(argv: Sequence[str]) -> None:
    if os.name != "nt" or sys.flags.utf8_mode:
        return

    completed_process = subprocess.run(
        [sys.executable, "-X", "utf8", Path(__file__).resolve(), *argv],
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )
    raise SystemExit(completed_process.returncode)


def prepend_env_path(path_value: str | Path) -> None:
    resolved_path = str(path_value)
    current_path = os.environ.get("PATH", "")
    path_entries = current_path.split(os.pathsep) if current_path else []
    normalized_entries = {os.path.normcase(entry) for entry in path_entries}
    if os.path.normcase(resolved_path) in normalized_entries:
        return
    os.environ["PATH"] = os.pathsep.join([resolved_path, *path_entries]) if path_entries else resolved_path


def ensure_ninja_on_path() -> None:
    prepend_env_path(Path(sys.executable).resolve().parent)
    try:
        import ninja
    except ImportError:
        return

    ninja_bin_dir = getattr(ninja, "BIN_DIR", None)
    if ninja_bin_dir:
        prepend_env_path(ninja_bin_dir)


def resolve_render_preview_device(device: str | None = None) -> str:
    if device is not None:
        return device
    if torch.cuda.is_available():
        return "cuda"
    raise RuntimeError("CUDA is required for gsplat preview rendering, but no CUDA device is available.")


def build_preview_output_path(
    output_path: str | Path = DEFAULT_RENDER_PREVIEW_OUTPUT_PATH,
) -> Path:
    resolved_path = Path(output_path)
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def build_preview_intrinsics(
    *,
    width: int,
    height: int,
    focal_length: float,
    device: str,
) -> torch.Tensor:
    validate_image_size(width, height)
    return torch.tensor(
        [
            [focal_length, 0.0, width / 2.0],
            [0.0, focal_length, height / 2.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=torch.float32,
        device=device,
    )[None]


def build_look_at_view_matrix(
    eye: Sequence[float] | torch.Tensor,
    target: Sequence[float] | torch.Tensor,
    *,
    up: Sequence[float] = (0.0, 0.0, 1.0),
    device: str,
) -> torch.Tensor:
    eye_tensor = torch.as_tensor(eye, dtype=torch.float32, device=device)
    target_tensor = torch.as_tensor(target, dtype=torch.float32, device=device)
    up_tensor = torch.as_tensor(up, dtype=torch.float32, device=device)

    forward = target_tensor - eye_tensor
    forward = forward / torch.linalg.norm(forward)

    right = torch.cross(forward, up_tensor, dim=0)
    right = right / torch.linalg.norm(right)

    true_up = torch.cross(right, forward, dim=0)
    true_up = true_up / torch.linalg.norm(true_up)

    camera_to_world = torch.eye(4, dtype=torch.float32, device=device)
    camera_to_world[:3, 0] = right
    camera_to_world[:3, 1] = true_up
    camera_to_world[:3, 2] = forward
    camera_to_world[:3, 3] = eye_tensor
    return torch.linalg.inv(camera_to_world)


def build_preview_view_matrix(
    means: torch.Tensor,
    *,
    device: str,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    camera_offset: CameraOffsetState = CameraOffsetState(),
) -> torch.Tensor:
    camera_state = build_preview_camera_state(
        means,
        width=width,
        height=height,
        focal_length=focal_length,
        device=device,
        camera_offset=camera_offset,
    )
    return build_look_at_view_matrix(
        camera_state.eye,
        camera_state.target,
        up=camera_state.up,
        device=device,
    )[None]


def save_render_preview_image(
    rgb8_image: np.ndarray,
    output_path: str | Path = DEFAULT_RENDER_PREVIEW_OUTPUT_PATH,
) -> Path:
    from PIL import Image

    resolved_path = build_preview_output_path(output_path)
    Image.fromarray(np.ascontiguousarray(rgb8_image, dtype=np.uint8)).save(resolved_path)
    return resolved_path


def render_gaussian_splat_preview_output(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
    robot_states: Sequence[RobotState] = (),
) -> tuple[np.ndarray, PreviewCameraState]:
    rasterization = require_gsplat_rasterization()
    resolved_device = resolve_render_preview_device(device)
    ensure_ninja_on_path()
    if shutil.which("ninja") is None:
        raise RuntimeError(
            "gsplat requires the `ninja` executable to JIT compile its CUDA extension, "
            "but it was not found on PATH."
        )
    model = load_gaussian_splat_model(
        ply_path,
        device=resolved_device,
        max_vertices=max_vertices,
    )
    intrinsics = build_preview_intrinsics(
        width=width,
        height=height,
        focal_length=focal_length,
        device=resolved_device,
    )
    preview_camera_state = build_preview_camera_state(
        model.means,
        width=width,
        height=height,
        focal_length=focal_length,
        device=resolved_device,
        camera_offset=camera_offset,
    )
    view_matrix = build_look_at_view_matrix(
        preview_camera_state.eye,
        preview_camera_state.target,
        up=preview_camera_state.up,
        device=resolved_device,
    )[None]

    try:
        with torch.inference_mode():
            render_colors, _render_alphas, _meta = rasterization(
                means=model.means,
                quats=model.quats,
                scales=model.scales,
                opacities=model.opacities,
                colors=model.colors,
                viewmats=view_matrix,
                Ks=intrinsics,
                width=width,
                height=height,
                sh_degree=model.sh_degree,
                render_mode="RGB",
                packed=False,
            )
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            "gsplat failed while decoding Windows compiler output during CUDA extension build. "
            "Inspect the torch_extensions build directory for the underlying compiler error."
        ) from exc
    except RuntimeError as exc:
        if "Ninja is required to load C++ extensions" in str(exc):
            raise RuntimeError(
                "gsplat requires `ninja` to JIT compile its CUDA extension. "
                "Install it in apps/render/.venv with `pip install ninja` and re-run the preview."
            ) from exc
        raise

    rgb = render_colors[0].clamp(0.0, 1.0).detach().cpu().numpy()
    rgb8_image = np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8)
    if robot_states:
        rgb8_image = overlay_robot_states_on_preview_frame(
            rgb8_image,
            preview_camera_state=preview_camera_state,
            robot_states=robot_states,
        )
    return rgb8_image, preview_camera_state


def render_gaussian_splat_preview_image(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
    robot_states: Sequence[RobotState] = (),
) -> np.ndarray:
    rgb8_image, _preview_camera_state = render_gaussian_splat_preview_output(
        ply_path=ply_path,
        device=device,
        width=width,
        height=height,
        focal_length=focal_length,
        max_vertices=max_vertices,
        camera_offset=camera_offset,
        robot_states=robot_states,
    )
    return rgb8_image


def render_gaussian_splat_preview_frame(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
    robot_states: Sequence[RobotState] = (),
) -> RenderedPreviewFrame:
    return render_gaussian_splat_preview_result(
        ply_path=ply_path,
        device=device,
        width=width,
        height=height,
        focal_length=focal_length,
        max_vertices=max_vertices,
        camera_offset=camera_offset,
        robot_states=robot_states,
    ).frame


def render_gaussian_splat_preview_result(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
    robot_states: Sequence[RobotState] = (),
) -> PreviewRenderResult:
    rgb8_image, preview_camera_state = render_gaussian_splat_preview_output(
        ply_path=ply_path,
        device=device,
        width=width,
        height=height,
        focal_length=focal_length,
        max_vertices=max_vertices,
        camera_offset=camera_offset,
        robot_states=robot_states,
    )
    return PreviewRenderResult(
        frame=build_rendered_preview_frame(rgb8_image),
        camera_state=preview_camera_state,
    )


def render_gaussian_splat_preview(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    output_path: str | Path = DEFAULT_RENDER_PREVIEW_OUTPUT_PATH,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
    robot_states: Sequence[RobotState] = (),
) -> Path:
    return save_render_preview_image(
        render_gaussian_splat_preview_image(
            ply_path=ply_path,
            device=device,
            width=width,
            height=height,
            focal_length=focal_length,
            max_vertices=max_vertices,
            camera_offset=camera_offset,
            robot_states=robot_states,
        ),
        output_path,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load a configured Gaussian splat PLY with gsplat and save a PNG preview.",
    )
    parser.add_argument(
        "--config-path",
        type=Path,
        default=DEFAULT_RENDER_CONFIG_PATH,
        help="Path to the preview render config JSON file.",
    )
    parser.add_argument(
        "--ply-path",
        type=Path,
        default=None,
        help="Path to the Gaussian splat PLY file.",
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=DEFAULT_RENDER_PREVIEW_OUTPUT_PATH,
        help="Path where the rendered preview PNG will be written.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Torch device to use. Defaults to cuda when available.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=DEFAULT_RENDER_PREVIEW_WIDTH,
        help="Preview image width in pixels.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=DEFAULT_RENDER_PREVIEW_HEIGHT,
        help="Preview image height in pixels.",
    )
    parser.add_argument(
        "--focal-length",
        type=float,
        default=None,
        help="Camera focal length in pixels.",
    )
    parser.add_argument(
        "--max-vertices",
        type=int,
        default=None,
        help="Optional vertex cap for faster preview renders.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    restart_in_utf8_mode_if_needed(effective_argv)
    args = build_argument_parser().parse_args(effective_argv)
    preview_render_config = load_preview_render_config(args.config_path)
    resolved_ply_path = preview_render_config.ply_path if args.ply_path is None else args.ply_path
    resolved_focal_length = (
        preview_render_config.focal_length_px if args.focal_length is None else args.focal_length
    )
    robot_states = load_robot_states(args.config_path)
    output_path = render_gaussian_splat_preview(
        ply_path=resolved_ply_path,
        output_path=args.output_path,
        device=args.device,
        width=args.width,
        height=args.height,
        focal_length=resolved_focal_length,
        max_vertices=args.max_vertices,
        robot_states=robot_states,
    )
    print(
        f"Rendered {resolved_ply_path} to {output_path}",
        flush=True,
    )
    return 0


def notify_state_change(
    state_change_callback: StateChangeCallback | None,
    state: RenderWorkerState,
) -> None:
    if state_change_callback is not None:
        state_change_callback(state)


def run_render_loop(
    stop_event: Event,
    state_change_callback: StateChangeCallback | None = None,
    initialize_rendering: RenderInitializationStep | None = None,
    render_frame: RenderFrameStep | None = None,
    publish_frame: FramePublishCallback | None = None,
    consume_camera_update: CameraUpdateCallback | None = None,
    camera_poll_interval_s: float = 0.1,
) -> None:
    current_state = RenderWorkerState()
    rendered_frame: RenderedPreviewFrame | None = None

    if stop_event.is_set():
        return

    try:
        current_state = build_render_worker_state(RenderLifecycleState.LOADING)
        notify_state_change(state_change_callback, current_state)

        if initialize_rendering is not None:
            initialize_rendering()

        if stop_event.is_set():
            return

        current_state = build_render_worker_state(RenderLifecycleState.RENDERING)
        notify_state_change(state_change_callback, current_state)
        if render_frame is not None:
            rendered_frame = render_frame()

        if stop_event.is_set():
            return

        current_state = build_render_worker_state(RenderLifecycleState.COMPLETED)
        notify_state_change(state_change_callback, current_state)
        if rendered_frame is not None and publish_frame is not None:
            publish_frame(rendered_frame)

        if consume_camera_update is None:
            stop_event.wait()
            return

        while not stop_event.wait(camera_poll_interval_s):
            if not consume_camera_update():
                continue

            current_state = build_render_worker_state(RenderLifecycleState.RENDERING)
            notify_state_change(state_change_callback, current_state)
            if render_frame is not None:
                rendered_frame = render_frame()

            if stop_event.is_set():
                return

            current_state = build_render_worker_state(RenderLifecycleState.COMPLETED)
            notify_state_change(state_change_callback, current_state)
            if rendered_frame is not None and publish_frame is not None:
                publish_frame(rendered_frame)
    except Exception:
        current_state = build_render_worker_state(RenderLifecycleState.ERROR)
        notify_state_change(state_change_callback, current_state)
        stop_event.set()
        raise
    finally:
        if current_state.lifecycle not in (
            RenderLifecycleState.IDLE,
            RenderLifecycleState.ERROR,
        ):
            notify_state_change(
                state_change_callback,
                build_render_worker_state(RenderLifecycleState.IDLE),
            )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        print(f"Preview render failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from exc
