# render_ply_with_gsplat.py
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from plyfile import PlyData
from gsplat.rendering import rasterization

SH_C0 = 0.28209479177387814


def load_gs_ply(ply_path: str, device: str = "cuda"):
    ply = PlyData.read(ply_path)
    v = ply["vertex"]

    names = set(v.data.dtype.names)

    def col(name):
        return np.asarray(v[name], dtype=np.float32)

    # positions
    means = np.stack([col("x"), col("y"), col("z")], axis=1)

    # scales
    scales = np.stack(
        [col("scale_0"), col("scale_1"), col("scale_2")],
        axis=1,
    )

    # rotations (quaternion)
    quats = np.stack(
        [col("rot_0"), col("rot_1"), col("rot_2"), col("rot_3")],
        axis=1,
    )

    # opacity
    opacities = col("opacity")

    # colors:
    # 3DGS PLY often stores SH DC terms as f_dc_0..2.
    # If not present, fall back to uint8 RGB.
    if {"f_dc_0", "f_dc_1", "f_dc_2"}.issubset(names):
        sh_dc = np.stack(
            [col("f_dc_0"), col("f_dc_1"), col("f_dc_2")],
            axis=1,
        )
        # Postshot exports the DC spherical harmonics coefficients, not plain RGB.
        colors = sh_dc * SH_C0 + 0.5
    elif {"red", "green", "blue"}.issubset(names):
        colors = np.stack(
            [col("red"), col("green"), col("blue")],
            axis=1,
        ) / 255.0
    else:
        raise ValueError(
            "PLY に色属性がありません。"
            " f_dc_0..2 か red/green/blue が必要です。"
        )

    means = torch.tensor(means, dtype=torch.float32, device=device)
    scales = torch.tensor(scales, dtype=torch.float32, device=device)
    quats = torch.tensor(quats, dtype=torch.float32, device=device)
    opacities = torch.tensor(opacities, dtype=torch.float32, device=device)
    colors = torch.tensor(colors, dtype=torch.float32, device=device)

    # 3DGS-style PLY stores scales in log-space and opacity in logit-space.
    scales = torch.exp(scales)
    opacities = torch.sigmoid(opacities)

    # 念のため正規化
    quats = torch.nn.functional.normalize(quats, dim=-1)

    return means, quats, scales, opacities, colors


def look_at(eye, target, up=(0.0, 0.0, 1.0), device="cuda"):
    eye = torch.tensor(eye, dtype=torch.float32, device=device)
    target = torch.tensor(target, dtype=torch.float32, device=device)
    up = torch.tensor(up, dtype=torch.float32, device=device)

    forward = target - eye
    forward = forward / torch.linalg.norm(forward)

    right = torch.cross(forward, up, dim=0)
    right = right / torch.linalg.norm(right)

    true_up = torch.cross(right, forward, dim=0)
    true_up = true_up / torch.linalg.norm(true_up)

    # camera-to-world
    c2w = torch.eye(4, dtype=torch.float32, device=device)
    c2w[:3, 0] = right
    c2w[:3, 1] = true_up
    c2w[:3, 2] = forward
    c2w[:3, 3] = eye

    # gsplat example uses world-to-camera = c2w.inverse()
    viewmat = torch.linalg.inv(c2w)
    return viewmat


def main():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device != "cuda":
        raise RuntimeError("gsplat の実用描画は CUDA 前提です。")

    #ply_path = "./sample_data/Compressed_PLY(SuperSplat)/cactus_splat3_11kSteps_1.5M_splats.compressed.ply"
    ply_path = "../../assets/cactus_splat3_25kSteps_2M_splats.ply"
    out_path = "render.png"

    means, quats, scales, opacities, colors = load_gs_ply(ply_path, device=device)

    # シーン中心とサイズのざっくり推定
    center = means.mean(dim=0)
    radius = torch.linalg.norm(means - center, dim=1).quantile(0.95).item()

    # カメラ設定
    width, height = 1280, 720
    fx = fy = 900.0
    cx = width / 2.0
    cy = height / 2.0

    K = torch.tensor(
        [
            [fx, 0.0, cx],
            [0.0, fy, cy],
            [0.0, 0.0, 1.0],
        ],
        dtype=torch.float32,
        device=device,
    )[None]  # [1, 3, 3]

    eye = (center + torch.tensor([0.0, -2.5 * radius, 0.8 * radius], device=device)).tolist()
    target = center.tolist()
    viewmat = look_at(eye, target, up=(0.0, 0.0, 1.0), device=device)[None]  # [1, 4, 4]

    # 描画
    render_colors, render_alphas, meta = rasterization(
        means=means,           # [N, 3]
        quats=quats,           # [N, 4]
        scales=scales,         # [N, 3]
        opacities=opacities,   # [N]
        colors=colors,         # [N, 3]
        viewmats=viewmat,      # [1, 4, 4]
        Ks=K,                  # [1, 3, 3]
        width=width,
        height=height,
        render_mode="RGB",
        packed=False,
    )

    rgb = render_colors[0].clamp(0.0, 1.0).detach().cpu().numpy()
    img = (rgb * 255.0).astype(np.uint8)
    Image.fromarray(img).save(out_path)
    print(f"saved: {out_path}")


if __name__ == "__main__":
    main()
