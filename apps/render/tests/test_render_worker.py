from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
from PIL import Image
from plyfile import PlyData, PlyElement
from torch.utils import cpp_extension

import render_worker


class FakeStopEvent:
    def __init__(self, *, initially_set: bool = False) -> None:
        self._set = initially_set
        self.set_calls = 0
        self.wait_calls = 0

    def is_set(self) -> bool:
        return self._set

    def set(self) -> None:
        self._set = True
        self.set_calls += 1

    def wait(self, _timeout: float | None = None) -> bool:
        self._set = True
        self.wait_calls += 1
        return True


class SequencedStopEvent:
    def __init__(self, wait_results: list[bool]) -> None:
        self.wait_results = list(wait_results)
        self.set_calls = 0
        self.wait_calls = 0

    def is_set(self) -> bool:
        return False

    def set(self) -> None:
        self.set_calls += 1

    def wait(self, _timeout: float | None = None) -> bool:
        self.wait_calls += 1
        if not self.wait_results:
            raise AssertionError("wait called more times than expected")
        return self.wait_results.pop(0)


def test_run_render_loop_notifies_loading_rendering_and_idle_states() -> None:
    stop_event = FakeStopEvent()
    observed_states: list[render_worker.RenderWorkerState] = []

    render_worker.run_render_loop(stop_event, observed_states.append)

    assert observed_states == [
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.LOADING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.RENDERING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.COMPLETED),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.IDLE),
    ]
    assert stop_event.wait_calls == 1
    assert stop_event.set_calls == 0


def test_run_render_loop_notifies_error_and_requests_shutdown_on_failure() -> None:
    stop_event = FakeStopEvent()
    observed_states: list[render_worker.RenderWorkerState] = []

    def fail_initialization() -> None:
        raise RuntimeError("render bootstrap failed")

    with pytest.raises(RuntimeError, match="render bootstrap failed"):
        render_worker.run_render_loop(
            stop_event,
            observed_states.append,
            initialize_rendering=fail_initialization,
        )

    assert observed_states == [
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.LOADING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.ERROR),
    ]
    assert stop_event.wait_calls == 0
    assert stop_event.set_calls == 1


def test_run_render_loop_returns_immediately_when_stop_is_already_requested() -> None:
    stop_event = FakeStopEvent(initially_set=True)
    observed_states: list[render_worker.RenderWorkerState] = []

    render_worker.run_render_loop(stop_event, observed_states.append)

    assert observed_states == []
    assert stop_event.wait_calls == 0
    assert stop_event.set_calls == 0


def test_run_render_loop_renders_and_publishes_preview_frame_once() -> None:
    stop_event = FakeStopEvent()
    observed_states: list[render_worker.RenderWorkerState] = []
    published_frames: list[render_worker.RenderedPreviewFrame] = []
    rendered_frame = render_worker.RenderedPreviewFrame(
        width=2,
        height=1,
        payload=b"\x01\x02\x03\x04\x05\x06",
    )

    render_worker.run_render_loop(
        stop_event,
        observed_states.append,
        render_frame=lambda: rendered_frame,
        publish_frame=published_frames.append,
    )

    assert observed_states == [
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.LOADING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.RENDERING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.COMPLETED),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.IDLE),
    ]
    assert published_frames == [rendered_frame]
    assert stop_event.wait_calls == 1


def test_run_render_loop_rerenders_when_camera_update_is_consumed() -> None:
    stop_event = SequencedStopEvent([False, True])
    observed_states: list[render_worker.RenderWorkerState] = []
    published_frames: list[render_worker.RenderedPreviewFrame] = []
    rendered_frames = [
        render_worker.RenderedPreviewFrame(width=1, height=1, payload=b"\x00\x00\x00"),
        render_worker.RenderedPreviewFrame(width=1, height=1, payload=b"\xff\xff\xff"),
    ]
    render_calls = 0
    camera_update_calls = 0

    def fake_render_frame() -> render_worker.RenderedPreviewFrame:
        nonlocal render_calls
        frame = rendered_frames[render_calls]
        render_calls += 1
        return frame

    def consume_camera_update() -> bool:
        nonlocal camera_update_calls
        camera_update_calls += 1
        return camera_update_calls == 1

    render_worker.run_render_loop(
        stop_event,  # type: ignore[arg-type]
        observed_states.append,
        render_frame=fake_render_frame,
        publish_frame=published_frames.append,
        consume_camera_update=consume_camera_update,
        camera_poll_interval_s=0.01,
    )

    assert observed_states == [
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.LOADING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.RENDERING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.COMPLETED),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.RENDERING),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.COMPLETED),
        render_worker.RenderWorkerState(render_worker.RenderLifecycleState.IDLE),
    ]
    assert published_frames == rendered_frames
    assert render_calls == 2
    assert stop_event.wait_calls == 2


def write_vertex_ply(path: Path, vertices: np.ndarray) -> None:
    PlyData([PlyElement.describe(vertices, "vertex")], text=False).write(path)


def test_load_gaussian_splat_model_transforms_sh_coefficients_and_gaussian_params(
    tmp_path: Path,
) -> None:
    ply_path = tmp_path / "sh_coefficients.ply"
    vertices = np.array(
        [
            (
                1.0,
                2.0,
                3.0,
                0.0,
                np.log(2.0),
                np.log(4.0),
                2.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                -1.0,
            ),
        ],
        dtype=[
            ("x", "f4"),
            ("y", "f4"),
            ("z", "f4"),
            ("scale_0", "f4"),
            ("scale_1", "f4"),
            ("scale_2", "f4"),
            ("rot_0", "f4"),
            ("rot_1", "f4"),
            ("rot_2", "f4"),
            ("rot_3", "f4"),
            ("opacity", "f4"),
            ("f_dc_0", "f4"),
            ("f_dc_1", "f4"),
            ("f_dc_2", "f4"),
        ],
    )
    write_vertex_ply(ply_path, vertices)

    model = render_worker.load_gaussian_splat_model(ply_path)

    assert model.ply_path == ply_path
    assert model.point_count == 1
    assert model.means.shape == (1, 3)
    assert model.quats.shape == (1, 4)
    assert model.scales.shape == (1, 3)
    assert model.opacities.shape == (1,)
    assert model.colors.shape == (1, 3)
    torch.testing.assert_close(
        model.means,
        torch.tensor([[1.0, 2.0, 3.0]], dtype=torch.float32),
    )
    torch.testing.assert_close(
        model.scales,
        torch.tensor([[1.0, 2.0, 4.0]], dtype=torch.float32),
    )
    torch.testing.assert_close(
        model.opacities,
        torch.tensor([0.5], dtype=torch.float32),
    )
    torch.testing.assert_close(
        model.quats,
        torch.tensor([[1.0, 0.0, 0.0, 0.0]], dtype=torch.float32),
    )
    torch.testing.assert_close(
        model.colors,
        torch.tensor(
            [[
                0.5,
                0.5 + render_worker.SH_C0,
                0.5 - render_worker.SH_C0,
            ]],
            dtype=torch.float32,
        ),
    )


def test_load_gaussian_splat_model_falls_back_to_rgb_colors(tmp_path: Path) -> None:
    ply_path = tmp_path / "rgb_colors.ply"
    vertices = np.array(
        [
            (
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                255,
                128,
                0,
            ),
        ],
        dtype=[
            ("x", "f4"),
            ("y", "f4"),
            ("z", "f4"),
            ("scale_0", "f4"),
            ("scale_1", "f4"),
            ("scale_2", "f4"),
            ("rot_0", "f4"),
            ("rot_1", "f4"),
            ("rot_2", "f4"),
            ("rot_3", "f4"),
            ("opacity", "f4"),
            ("red", "u1"),
            ("green", "u1"),
            ("blue", "u1"),
        ],
    )
    write_vertex_ply(ply_path, vertices)

    model = render_worker.load_gaussian_splat_model(ply_path)

    torch.testing.assert_close(
        model.colors,
        torch.tensor([[1.0, 128.0 / 255.0, 0.0]], dtype=torch.float32),
    )


def test_load_gaussian_splat_model_rejects_missing_color_fields(tmp_path: Path) -> None:
    ply_path = tmp_path / "missing_colors.ply"
    vertices = np.array(
        [
            (
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
            ),
        ],
        dtype=[
            ("x", "f4"),
            ("y", "f4"),
            ("z", "f4"),
            ("scale_0", "f4"),
            ("scale_1", "f4"),
            ("scale_2", "f4"),
            ("rot_0", "f4"),
            ("rot_1", "f4"),
            ("rot_2", "f4"),
            ("rot_3", "f4"),
            ("opacity", "f4"),
        ],
    )
    write_vertex_ply(ply_path, vertices)

    with pytest.raises(ValueError, match="color"):
        render_worker.load_gaussian_splat_model(ply_path)


def test_load_gaussian_splat_model_can_limit_vertices_for_large_assets() -> None:
    model = render_worker.load_gaussian_splat_model(
        render_worker.DEFAULT_GAUSSIAN_SPLAT_PLY_PATH,
        max_vertices=8,
    )

    assert model.ply_path == render_worker.DEFAULT_GAUSSIAN_SPLAT_PLY_PATH
    assert model.point_count == 8
    assert model.means.shape == (8, 3)
    assert model.quats.shape == (8, 4)
    assert model.scales.shape == (8, 3)
    assert model.opacities.shape == (8,)
    assert model.colors.shape == (8, 3)
    assert model.means.device.type == "cpu"


def test_build_preview_intrinsics_uses_image_center_as_principal_point() -> None:
    intrinsics = render_worker.build_preview_intrinsics(
        width=640,
        height=360,
        focal_length=500.0,
        device="cpu",
    )

    torch.testing.assert_close(
        intrinsics,
        torch.tensor(
            [
                [
                    [500.0, 0.0, 320.0],
                    [0.0, 500.0, 180.0],
                    [0.0, 0.0, 1.0],
                ]
            ],
            dtype=torch.float32,
        ),
    )


def test_build_rendered_preview_frame_uses_rgb8_image_dimensions() -> None:
    frame = render_worker.build_rendered_preview_frame(
        np.array(
            [
                [[255, 0, 0], [0, 255, 0]],
                [[0, 0, 255], [255, 255, 255]],
            ],
            dtype=np.uint8,
        )
    )

    assert frame.width == 2
    assert frame.height == 2
    assert frame.payload == (
        b"\xff\x00\x00"
        b"\x00\xff\x00"
        b"\x00\x00\xff"
        b"\xff\xff\xff"
    )


def test_build_preview_view_matrix_applies_camera_offset_in_radius_units() -> None:
    means = torch.tensor(
        [
            [0.0, 0.0, 0.0],
            [2.0, 0.0, 0.0],
        ],
        dtype=torch.float32,
    )

    without_offset = render_worker.build_preview_view_matrix(means, device="cpu")
    with_offset = render_worker.build_preview_view_matrix(
        means,
        device="cpu",
        camera_offset=render_worker.CameraOffsetState(offset_x=0.5, offset_z=0.25),
    )

    assert without_offset.shape == (1, 4, 4)
    assert with_offset.shape == (1, 4, 4)
    assert not torch.equal(without_offset, with_offset)


def test_render_gaussian_splat_preview_saves_png_with_stubbed_rasterization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output_path = tmp_path / "preview.png"
    means = torch.tensor(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=torch.float32,
    )
    model = render_worker.GaussianSplatModel(
        ply_path=tmp_path / "model.ply",
        means=means,
        quats=torch.tensor(
            [
                [1.0, 0.0, 0.0, 0.0],
                [1.0, 0.0, 0.0, 0.0],
            ],
            dtype=torch.float32,
        ),
        scales=torch.ones((2, 3), dtype=torch.float32),
        opacities=torch.ones(2, dtype=torch.float32),
        colors=torch.tensor(
            [
                [1.0, 0.0, 0.0],
                [0.0, 1.0, 0.0],
            ],
            dtype=torch.float32,
        ),
    )
    captured_args: dict[str, object] = {}

    def fake_load_gaussian_splat_model(
        ply_path: str | Path,
        *,
        device: str = "cpu",
        max_vertices: int | None = None,
    ) -> render_worker.GaussianSplatModel:
        captured_args["ply_path"] = Path(ply_path)
        captured_args["device"] = device
        captured_args["max_vertices"] = max_vertices
        return model

    def fake_rasterization(**kwargs):
        captured_args["rasterization_width"] = kwargs["width"]
        captured_args["rasterization_height"] = kwargs["height"]
        height = int(kwargs["height"])
        width = int(kwargs["width"])
        colors = torch.full((1, height, width, 3), 0.25, dtype=torch.float32)
        alphas = torch.ones((1, height, width, 1), dtype=torch.float32)
        return colors, alphas, {"stub": True}

    monkeypatch.setattr(render_worker, "load_gaussian_splat_model", fake_load_gaussian_splat_model)
    monkeypatch.setattr(render_worker, "require_gsplat_rasterization", lambda: fake_rasterization)

    resolved_output_path = render_worker.render_gaussian_splat_preview(
        ply_path=tmp_path / "input.ply",
        output_path=output_path,
        device="cpu",
        width=32,
        height=24,
        max_vertices=128,
    )

    assert resolved_output_path == output_path
    assert output_path.is_file()
    assert captured_args == {
        "ply_path": tmp_path / "input.ply",
        "device": "cpu",
        "max_vertices": 128,
        "rasterization_width": 32,
        "rasterization_height": 24,
    }

    with Image.open(output_path) as image:
        assert image.size == (32, 24)


def test_restart_in_utf8_mode_if_needed_reexecutes_on_windows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_command: dict[str, object] = {}

    def fake_run(command, check: bool, env: dict[str, str]):
        captured_command["command"] = command
        captured_command["check"] = check
        captured_command["env"] = env
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(render_worker.os, "name", "nt")
    monkeypatch.setattr(render_worker.sys, "executable", "python.exe")
    monkeypatch.setattr(render_worker.sys, "flags", SimpleNamespace(utf8_mode=0))
    monkeypatch.setattr(render_worker.subprocess, "run", fake_run)

    with pytest.raises(SystemExit) as excinfo:
        render_worker.restart_in_utf8_mode_if_needed(["--max-vertices", "16"])

    assert excinfo.value.code == 7
    assert captured_command["command"] == [
        "python.exe",
        "-X",
        "utf8",
        Path(render_worker.__file__).resolve(),
        "--max-vertices",
        "16",
    ]
    assert captured_command["check"] is False
    assert captured_command["env"]["PYTHONUTF8"] == "1"


def test_prepend_env_path_adds_path_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    existing_path = os.pathsep.join(["C:\\existing", "C:\\second"])
    monkeypatch.setenv("PATH", existing_path)

    render_worker.prepend_env_path("C:\\new")
    render_worker.prepend_env_path("C:\\new")

    assert os.environ["PATH"].split(os.pathsep) == [
        "C:\\new",
        "C:\\existing",
        "C:\\second",
    ]


def test_patch_torch_cpp_extension_for_windows_removes_gnu_warning_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_jit_compile(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return "compiled"

    monkeypatch.setattr(render_worker.os, "name", "nt")
    monkeypatch.setattr(cpp_extension, "_jit_compile", fake_jit_compile)

    render_worker.patch_torch_cpp_extension_for_windows()
    result = cpp_extension._jit_compile(
        "gsplat_cuda",
        [],
        ["-O3", "-Wno-attributes"],
        None,
        None,
        None,
        None,
        False,
    )

    assert result == "compiled"
    assert captured["args"][2] == ["-O3"]
