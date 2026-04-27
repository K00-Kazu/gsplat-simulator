# アーキテクチャ概要

## 目的
本ドキュメントは、現行の preview-only 構成を次の最小機能まで拡張する前提で、先に固定すべき責務分離と config 契約を整理する。

- シーンへのロボット表示
- ロボット中心基準の rig を持つ最大 4 カメラ / ロボット
- fisheye 想定の内部パラメータと歪み係数
- preview と robot camera の UI 分離
- UI からのロボット平行移動 / 回転

## 今回の設計判断
- `SimulationCore` を唯一の正規 state 所有者とし、scene / robot / preview camera / sensor camera の状態を一元管理する
- `Preview camera` と `robot-mounted sensor camera` は別責務として扱う
- ロボット本体は UI-only overlay ではなく、RenderWorker が生成する出力に載る形を基本とする
- `render.dev.json` は静的設定、UI 操作で変わる pose は runtime state として分離する
- config 保存処理は未知セクションを保持し、将来の `robots` / `distortion` 情報を消さない

## コンポーネント責務

### UI
- preview panel を表示する
- robot camera panel を 2x2 で表示する
- selected robot への移動 / 回転 command を送る
- preview camera 専用の操作を送る
- preview 専用の gizmo / debug overlay を描く

### SimulationCore
- scene / robot / camera の canonical state を持つ
- robot pose と camera rig から各 sensor camera の world pose を算出する
- config load / save の正規窓口になる
- UI command を解釈し、RenderWorker へ render request を組み立てる
- preview stream と robot stream の routing を行う

### RenderWorker
- Gaussian splatting の scene render を行う
- preview camera と robot camera を同じ state snapshot から描画する
- ロボット簡易表示用の cuboid overlay を描画する
- fisheye / distortion を反映した sensor image を生成する

### Transport
- topic namespace と publish / subscribe 契約を提供する
- UI / Core / RenderWorker が topic 命名を共有できるようにする

## ドメインモデル

### Preview camera
- 用途: シーン全体確認
- 操作主体: UI
- 表示先: メイン panel
- overlay: gizmo あり

### Robot
- `robot_id`
- `body.size_m`
- `body.color_rgba`
- `pose.position_m`
- `pose.yaw_pitch_roll_deg`

### Robot camera rig
- `camera_id`
- `panel_slot`
- `mount_pose.position_m`
- `mount_pose.yaw_pitch_roll_deg`
- `projection`
- `distortion`

### Frame route
各フレームは topic 名だけではなく metadata でも識別する。

- `stream_role`: `preview` | `robot`
- `robot_id`: preview では省略可
- `camera_id`
- `panel_slot`
- `frame_id`

## ロボット簡易表示の置き場所
最初のロボット表示は cuboid の簡易描画でよいが、描画責務は UI ではなく RenderWorker 側に置く。

理由:
- preview と transport 出力で見える内容を一致させやすい
- 将来 robot camera 側にも同じ primitive を使い回せる
- UI を 3D scene renderer にしなくてよい

初期実装では、gaussian scene との完全な深度整合までは求めない。まずは camera pose から投影した box overlay を stable に出すことを優先する。

## 設定ファイルの境界

### `config/render.dev.json`
保持するもの:
- preview の scene path と既定 optics
- robot 定義
- camera rig
- 画像サイズ
- 内部パラメータ
- distortion 係数

保持しないもの:
- 実行中の robot pose
- selected robot
- panel の一時的な UI 状態

### `config/transport.dev.json` / `config/transport.dev.json5`
保持するもの:
- topic namespace
- preview / robot / command / state の配線

保持しないもの:
- カメラ内部パラメータ
- robot rig
- シーンや pose

## 推奨 render config スキーマ
`render.dev.json` は preview だけでなく、将来の robot camera 設定を持てる形にしておく。

```json
{
  "preview": {
    "ply_path": "assets/sample_point_cloud.ply",
    "focal_length_px": 1296.98,
    "image_width": 1280,
    "image_height": 720
  },
  "robots": [
    {
      "id": "robot_01",
      "body": {
        "shape": "box",
        "size_m": [0.6, 0.4, 0.3],
        "color_rgba": [0.18, 0.64, 0.87, 0.9]
      },
      "initial_pose": {
        "position_m": [0.0, 0.0, 0.15],
        "yaw_pitch_roll_deg": [0.0, 0.0, 0.0]
      },
      "cameras": [
        {
          "id": "front_left",
          "panel_slot": 0,
          "mount_pose": {
            "position_m": [0.24, 0.16, 0.18],
            "yaw_pitch_roll_deg": [0.0, 0.0, 35.0]
          },
          "projection": {
            "camera_model": "fisheye",
            "calibration_model": "opencv_fisheye",
            "image_width": 640,
            "image_height": 640,
            "intrinsics": {
              "fx": 320.0,
              "fy": 320.0,
              "cx": 320.0,
              "cy": 320.0,
              "skew": 0.0
            },
            "distortion": {
              "k1": 0.0,
              "k2": 0.0,
              "k3": 0.0,
              "k4": 0.0
            }
          }
        }
      ]
    }
  ]
}
```

## メッセージング方針

### 維持する preview 系 topic
- `simulation/ui/preview/frame_metadata`
- `simulation/ui/preview/frame_payload`
- `simulation/ui/preview/camera_state`

### 追加する robot 系 topic
固定 camera ID ごとの topic を増やすのではなく、robot 系は多重化ストリームに寄せる。

- `simulation/ui/robot/frame_metadata`
- `simulation/ui/robot/frame_payload`
- `simulation/ui/robot/camera_state`  
  初回実装では optional

robot metadata には少なくとも次を含める。

- `robot_id`
- `camera_id`
- `panel_slot`
- `stream_role`

この方針にすると、要件が「最大 4 カメラ / ロボット」である以上、将来複数 robot に拡張しても topic 数が爆発しにくい。

### 追加する command / state
- `simulation/ui/cmd/robot`
- `simulation/ui/state/robot`
- `simulation/render/request/robot_pose`

preview camera command と robot motion command は分ける。preview の `pan / orbit / zoom` と robot の `translate / rotate` は意味が違うため、同一 payload に混ぜない。

## fisheye / distortion の扱い
現在の renderer 実装は `Ks + viewmats` の pinhole 前提であり、robot camera の fisheye 要件を満たすには拡張が必要である。

設計方針:
- 設定値の canonical 形式は `intrinsics + distortion coefficients` として JSON に保持する
- 実際の描画は、最終的には RenderWorker 側で distortion-aware な camera model を使う
- OpenCV は calibration / validation / map 生成の基準実装として使う

この分離により、保存形式を OpenCV 互換寄りに保ちつつ、render backend は `gsplat` の機能を利用できる。

## OpenCV / gsplat 調査メモ
- OpenCV の `cv::fisheye` には `projectPoints`、`distortPoints`、`initUndistortRectifyMap`、`undistortImage` があるため、fisheye calibration と検証の基準実装として扱いやすい
- このリポジトリの `apps/render/requirements.txt` では `gsplat==1.5.3` を使用しており、公式ドキュメント上は `camera_model` に `fisheye` / `ftheta`、さらに `radial_coeffs` などの distortion parameter を渡せる
- ただし OpenCV fisheye と gsplat 側の coefficient semantics が完全一致するかは、round-trip の描画比較テストで確認してから固定する

## 実装順の推奨
1. config round-trip を壊さない保存処理にする
2. `render.dev.json` と `transport.dev.json` に robot / rig / robot topic の器を追加する
3. Core に `RobotSpec` / `RobotState` / `RobotCameraRigSpec` を入れる
4. preview とは別に robot render request を定義する
5. UI に robot panel と robot control を追加する
6. fisheye rendering を pinhole から切り替える

## 非目標
- 初回から可変台数の一般化をし切ること
- 初回から scene と robot cuboid の完全な occlusion 整合を出すこと
- UI を 3D editor にすること
