from __future__ import annotations

import argparse
import math
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from threading import Event
from typing import Callable, Sequence

import numpy as np
import torch
from plyfile import PlyData


SH_C0 = 0.28209479177387814
DEFAULT_GAUSSIAN_SPLAT_PLY_PATH = (
    Path(__file__).resolve().parents[2] / "assets" / "cactus_splat3_25kSteps_2M_splats.ply"
)
DEFAULT_RENDER_PREVIEW_OUTPUT_PATH = (
    Path(__file__).resolve().parents[2] / "runtime" / "cache" / "render_worker_preview.png"
)
DEFAULT_RENDER_PREVIEW_WIDTH = 1280
DEFAULT_RENDER_PREVIEW_HEIGHT = 720
DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH = 900.0
DEFAULT_RENDER_PREVIEW_CAMERA_DISTANCE_SCALE = 2.5
DEFAULT_RENDER_PREVIEW_CAMERA_HEIGHT_SCALE = 0.8


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

    @property
    def point_count(self) -> int:
        return int(self.means.shape[0])


@dataclass(frozen=True)
class RenderedPreviewFrame:
    width: int
    height: int
    payload: bytes


@dataclass(frozen=True)
class CameraOffsetState:
    offset_x: float = 0.0
    offset_y: float = 0.0
    offset_z: float = 0.0


StateChangeCallback = Callable[[RenderWorkerState], None]
RenderInitializationStep = Callable[[], None]
RenderFrameStep = Callable[[], RenderedPreviewFrame]
FramePublishCallback = Callable[[RenderedPreviewFrame], None]
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
        camera_offset.offset_x,
        camera_offset.offset_y,
        camera_offset.offset_z,
    )
    if not all(math.isfinite(value) for value in values):
        raise ValueError("camera offsets must be finite numbers")
    return camera_offset


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

    means = np.stack([column("x"), column("y"), column("z")], axis=1)
    scales = np.stack([column("scale_0"), column("scale_1"), column("scale_2")], axis=1)
    quats = np.stack([column("rot_0"), column("rot_1"), column("rot_2"), column("rot_3")], axis=1)
    opacities = column("opacity")

    sh_color_fields = {"f_dc_0", "f_dc_1", "f_dc_2"}
    rgb_color_fields = {"red", "green", "blue"}
    if sh_color_fields.issubset(names):
        sh_dc = np.stack([column("f_dc_0"), column("f_dc_1"), column("f_dc_2")], axis=1)
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
    camera_offset: CameraOffsetState = CameraOffsetState(),
) -> torch.Tensor:
    resolved_camera_offset = validate_camera_offset_state(camera_offset)
    center = means.mean(dim=0)
    distances = torch.linalg.norm(means - center, dim=1)
    radius = max(float(torch.quantile(distances, 0.95).item()), 1e-3)
    default_eye_offset = torch.tensor(
        [
            0.0,
            -DEFAULT_RENDER_PREVIEW_CAMERA_DISTANCE_SCALE * radius,
            DEFAULT_RENDER_PREVIEW_CAMERA_HEIGHT_SCALE * radius,
        ],
        dtype=torch.float32,
        device=device,
    )
    eye = center + default_eye_offset + torch.tensor(
        [
            resolved_camera_offset.offset_x * radius,
            resolved_camera_offset.offset_y * radius,
            resolved_camera_offset.offset_z * radius,
        ],
        dtype=torch.float32,
        device=device,
    )
    return build_look_at_view_matrix(
        eye,
        center,
        up=(0.0, 0.0, 1.0),
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


def render_gaussian_splat_preview_image(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
) -> np.ndarray:
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
    view_matrix = build_preview_view_matrix(
        model.means,
        device=resolved_device,
        camera_offset=camera_offset,
    )

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
    return np.clip(rgb * 255.0, 0.0, 255.0).astype(np.uint8)


def render_gaussian_splat_preview_frame(
    ply_path: str | Path = DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
    *,
    device: str | None = None,
    width: int = DEFAULT_RENDER_PREVIEW_WIDTH,
    height: int = DEFAULT_RENDER_PREVIEW_HEIGHT,
    focal_length: float = DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
    max_vertices: int | None = None,
    camera_offset: CameraOffsetState = CameraOffsetState(),
) -> RenderedPreviewFrame:
    return build_rendered_preview_frame(
        render_gaussian_splat_preview_image(
            ply_path=ply_path,
            device=device,
            width=width,
            height=height,
            focal_length=focal_length,
            max_vertices=max_vertices,
            camera_offset=camera_offset,
        )
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
        ),
        output_path,
    )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Load the default Gaussian splat PLY with gsplat and save a PNG preview.",
    )
    parser.add_argument(
        "--ply-path",
        type=Path,
        default=DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
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
        default=DEFAULT_RENDER_PREVIEW_FOCAL_LENGTH,
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
    output_path = render_gaussian_splat_preview(
        ply_path=args.ply_path,
        output_path=args.output_path,
        device=args.device,
        width=args.width,
        height=args.height,
        focal_length=args.focal_length,
        max_vertices=args.max_vertices,
    )
    print(
        f"Rendered {args.ply_path} to {output_path}",
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
