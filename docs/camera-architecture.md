# Camera Architecture Implementation Plan

## Status
Phase 0-2 implemented. Phase 3-4 planned.

## Date
2026-04-15

## Context
現在の UI は preview frame を画像として受信し、preview camera の `pan_x / pan_y / pan_z / yaw_degrees / pitch_degrees` を RenderWorker に送る thin client として実装されている。  
この構成は「シーン全体をざっと確認する preview UI」としては成立している一方で、次の課題がある。

- UI が受け取るのは実質 RGB frame と最小メタデータだけで、camera pose や world axis を持っていない
- pan と rotate が分かれていないと、world-space の平行移動とカメラ姿勢変更の違いを UI 上で確認しづらい
- 将来の robot camera 追加を考えると、preview camera と sensor camera の責務が未分離

本ドキュメントは、preview camera と robot camera を分離した中期アーキテクチャの実装計画を定義する。

## Requirements
- 現在実装されているカメラは `preview camera` として扱い、シーン全体を映す
- 各 robot には最大 4 台の `robot camera` を搭載できるようにしたい
- `robot camera` は別パネルで並列表示したい
- camera rig は robot 中心基準の相対 pose を config で与えたい
- robot camera は fisheye 想定で、内部パラメータと distortion を config に保存したい
- gizmo の表示対象は `preview camera` のみとする

## Goals
- preview camera と robot camera の責務を明確に分離する
- preview camera では UI overlay として gizmo を描画できるようにする
- robot と robot-mounted camera rig を first-class な state として扱う
- robot camera を `最大 4 台 / robot` まで拡張できる transport / UI / render contract を先に定義する
- 現在の `simulation/ui/preview/*` topic をできるだけ壊さずに拡張する
- render config を将来拡張しても preview 設定保存で壊れないようにする

## Non-Goals
- UI をフル機能の 3D editor / viewer に置き換えること
- robot camera に gizmo やインタラクティブな camera control を付けること
- 初回実装で可変台数の robot camera を一般化し切ること

## Architectural Decision

### 1. Camera Role を分離する
カメラは少なくとも次の 2 種類に分離する。

| Role | Purpose | UI 表示 | 操作主体 | Gizmo |
|---|---|---|---|---|
| `preview` | シーン全体の確認、開発用の見下ろし視点 | メイン preview panel | UI | 有効 |
| `robot` | ロボット搭載センサ視点、運用上の観測カメラ | 2x2 robot panel | SimulationCore / Robot state | 無効 |

### 2. 画像ストリームとカメラ状態は別契約にする
現在の image-only contract は preview 表示には十分だが、gizmo や camera semantics を UI に渡すには不十分である。  
そのため、frame と camera state を別 topic / 別 message として扱う。

- Frame stream: `frame_metadata` + `frame_payload`
- Camera state stream: `camera_state`

この分離により、UI は画像表示の責務を維持しながら、preview camera に限って overlay を描画できる。

### 3. Gizmo は RenderWorker 焼き込みではなく UI overlay に置く
中期案では gizmo は preview image に焼き込まない。  
理由は次の通り。

- preview のみ gizmo を出すという要件を素直に満たせる
- robot panel では同じ frame をそのまま再利用できる
- gizmo の色、配置、ON/OFF を UI 側で調整できる
- 将来 camera debug overlay を足しても RenderWorker の画像生成責務を増やしすぎない

### 4. Robot と camera rig は camera topic ではなく state で表現する
今回の要件は「4 カメラ固定」ではなく「最大 4 カメラ / robot」である。  
そのため contract 上の主語は camera 単体ではなく `robot + rig + sensor` とする。

- `RobotState`: world pose
- `RobotCameraRigSpec`: robot 基準の相対 pose
- `RobotCameraProjectionSpec`: intrinsics / distortion

RenderWorker は camera world pose を自前で保持するのではなく、Core が解決した state snapshot を受け取る。

## Current State

### Preview Camera
- RenderWorker は preview target を基準にした `look-at` camera を使う
- pan は preview target を world-space で移動させる
- rotate は yaw / pitch で eye と up を更新し、preview target の周囲を orbit する
- UI は preview 情報として RGB frame、frame metadata、preview camera state を受信する

### Data Flow
- RenderWorker → Core: `simulation/core/frame_metadata`, `simulation/core/frame_payload`
- Core → UI: `simulation/ui/preview/frame_metadata`, `simulation/ui/preview/frame_payload`
- UI → Core → RenderWorker: `simulation/ui/cmd/camera` → `simulation/render/request/camera`

## Target Architecture

### Camera Streams
最終的に UI は preview stream 1 本と、robot sensor の多重化 stream を扱う。

- `preview/main`
- `robot/*`

robot panel は 2x2 固定でも、stream 契約は `robot_id` と `camera_id` を metadata に持つ多重化方式にする。  
これにより、単一 robot の 4 カメラ表示から始めても、将来複数 robot へ伸ばしやすい。

### UI Layout
- メイン領域: `preview camera`
- サイドまたは下段パネル: `robot camera` 4 面を 2x2 で表示
- gizmo は preview panel のみ
- camera controls は preview camera のみを操作する

### Responsibility Split

#### UI
- preview panel の frame と preview camera state を受信する
- preview panel に gizmo overlay を描画する
- robot panel 4 面に robot frame を表示する
- selected robot の平行移動 / 回転 command を送信する
- preview camera command と robot motion command を分離する

#### SimulationCore
- camera role / camera id / robot id の canonical routing を担う
- robot pose と rig から sensor camera の world pose を解決する
- preview / robot camera の topic namespace を管理する
- frame stream と camera state stream を UI 向けに中継する

#### RenderWorker
- preview camera frame を生成する
- preview camera state を publish する
- robot camera frame を生成する
- ロボット簡易表示用の cuboid overlay を描画する
- preview camera と robot camera の描画設定を内部で分離する

## Proposed Contracts

### 1. Preview Camera State
preview camera 用に新しい state message を追加する。

```json
{
  "frame_id": 42,
  "camera_role": "preview",
  "eye": [0.0, -12.5, 4.0],
  "target": [0.0, 0.0, 0.0],
  "up": [0.0, 0.0, 1.0],
  "scene_center": [0.0, 0.0, 0.0],
  "scene_radius": 5.0,
  "focal_length_px": 900.0,
  "image_width": 1280,
  "image_height": 720,
  "world_up_axis": "z",
  "gizmo_enabled": true
}
```

`frame_id` を含め、preview image と camera state を UI 側で対応づけられるようにする。

### 2. Robot Camera Frames
robot camera では最初は frame のみを必須とする。  
robot panel は gizmo を描かないため、preview camera ほど豊富な state を最初から要求しない。

ただし将来の debug 用に、robot camera にも state topic を追加できる命名規則にしておく。

robot frame metadata には少なくとも次を含める。

```json
{
  "frame_id": 42,
  "timestamp": "2026-04-15T12:34:56.789Z",
  "stream_role": "robot",
  "robot_id": "robot_01",
  "camera_id": "front_left",
  "panel_slot": 0,
  "width": 640,
  "height": 640,
  "stride": 1920,
  "pixel_format": "rgb8"
}
```

### 3. Robot Camera Config
robot camera の保存形式は topic ではなく config で定義する。

```json
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
```

### 4. Topic Plan
既存 preview topic は維持しつつ、以下を追加する。

#### Existing topics kept
- `simulation/ui/preview/frame_metadata`
- `simulation/ui/preview/frame_payload`

#### New preview topic
- `simulation/ui/preview/camera_state`

#### New robot topic namespace
- `simulation/ui/robot/frame_metadata`
- `simulation/ui/robot/frame_payload`
- `simulation/ui/robot/camera_state`  
  初回実装では optional。予約だけしてもよい。

#### Command topic split
既存の `simulation/ui/cmd/camera` は preview camera command として扱う。  
robot camera は UI 直接操作対象ではないため、camera 専用 command topic は増やさない。  
代わりに robot 操作用の command topic を追加する。

- `simulation/ui/cmd/robot`

## Planned UI Behavior

### Preview Camera
- 役割: scene overview
- 操作: UI ボタンまたは将来のドラッグ操作
- gizmo: 表示する
- overlay 情報:
  - XYZ axis
  - `Preview camera` ラベル
  - 必要であれば `world: Z-up`

### Robot Cameras
- 役割: sensor / operational view
- 操作: 初回実装では UI から直接動かさない
- gizmo: 表示しない
- panel:
  - 2x2 固定レイアウト
  - 各 panel に camera ID を表示

## Implementation Phases

### Phase 0: Terminology and Naming Cleanup
目的: 現在の preview camera を将来の robot camera と混同しない状態を作る。

作業:
- `preview camera` を明示した文言へ UI / docs を整理する
- 現在の `Up / Down / Left / Right` は少なくとも補助文言で `world X/Z offset` と分かるようにする

完了条件:
- 現在の camera controls が preview camera 専用であることが UI から分かる

実装メモ:
- UI 表記を `Preview camera` 前提に変更済み
- status bar に render subscriber 状態を移設済み

### Phase 1: Preview Camera State Contract
目的: preview camera gizmo を描くための状態契約を導入する。

作業:
- RenderWorker に `PreviewCameraState` serializer を追加する
- Core に `simulation/ui/preview/camera_state` の routing を追加する
- `frame_id` と preview state の対応を保証する

完了条件:
- UI が preview frame と同じ tick の camera state を購読できる

実装メモ:
- RenderWorker → Core → UI の `preview/camera_state` routing を追加済み
- `frame_id` と `timestamp` を frame と camera state に共通付与済み

### Phase 2: Preview Gizmo Overlay
目的: preview panel 上で gizmo を描けるようにする。

作業:
- UI に preview camera state subscriber を追加する
- preview image の上に 2D overlay として XYZ gizmo を描画する
- gizmo は preview panel にのみ表示する

完了条件:
- preview camera 操作時に gizmo の向きと camera state の変化を視覚的に確認できる
- robot panel には gizmo が出ない

実装メモ:
- preview panel に gizmo overlay を追加済み
- preview controls を `Pan` と `Rotate` に分離済み
- `Pan` は target translation、`Rotate` は yaw / pitch による camera pose 変更として実装済み

### Phase 3: Robot Camera Stream Expansion
目的: robot camera 4 面表示のための frame stream を追加する。

作業:
- Core に `RobotState` / `RobotCameraRigSpec` を追加する
- RenderWorker に robot camera 複数系統のレンダリング設定を追加する
- Core に `simulation/ui/robot/*` routing を追加する
- UI に 2x2 robot panel を追加する
- UI に selected robot の移動 / 回転 command を追加する

完了条件:
- 1 robot あたり 4 つまでの camera frame が独立 panel に表示される
- preview camera と robot camera の表示が混在しない

### Phase 4: Operational Hardening
目的: multi-camera 運用で壊れにくい contract にする。

作業:
- stream 単位の欠落 frame / stale frame の扱いを定義する
- panel ごとの loading / error state を追加する
- camera ID と UI panel slot の対応表を固定化する

完了条件:
- どれか 1 系統の robot camera が落ちても preview camera と他 panel が維持される

## Data Model Notes

### Why not keep image-only forever?
通常の 3D model viewer / simulation viewer で image-only transport は珍しくない。  
ただしそれだけだと次の機能が弱い。

- gizmo
- camera orientation の検証
- debug overlay
- view semantic の分離

そのため本プロジェクトでは `image-only preview` をやめるのではなく、`image + camera state` へ段階的に拡張する。

### Why keep robot camera image-first?
robot camera は sensor panel の性格が強く、まず重要なのは 4 面を安定表示できることだからである。  
preview camera と違い、初回要件では gizmo や interactive control を必要としない。

### Distortion backend notes
fisheye の canonical config は OpenCV 互換の intrinsics / distortion で保持する。  
ただし描画 backend は OpenCV 固定にせず、`gsplat` の distortion-aware camera model を使えるようにする。

この方針にする理由:
- calibration や実機合わせでは OpenCV 互換形式が扱いやすい
- render 時は `gsplat` 側で distortion を持てるなら視野欠損の少ない sensor render を作りやすい
- coefficient semantics が完全一致しない場合でも config schema を壊さず adapter で吸収できる

## Risks

### Frame / State mismatch
preview frame と camera state が別 topic になるため、`frame_id` を使った同期規約が必要。

### Render cost increase
robot camera 4 系統を追加すると RenderWorker の GPU コストが大きく増える。  
preview と robot を同じ render tick に束ねるか、優先度を分けるかは early benchmark が必要。

### Contract sprawl
preview と robot の差分を無秩序に増やすと topic と message が散らばる。  
camera role と camera id を contract 上で先に固定しつつ、topic は多重化で抑える。

## Open Questions
- 複数 robot を同時表示する前提で panel slot をどう割り当てるか
- 4 camera を毎 tick 同期更新するか、個別更新を許可するか
- robot camera にも後から `camera_state` を流すか
- robot cuboid を depth-aware に scene へ合成するか、初期は overlay で割り切るか
- OpenCV fisheye と gsplat fisheye / ftheta のどの組み合わせを正式対応にするか
- preview camera command を今後 `orbit / pan / zoom` へ広げるか

## Recommended First Slice
最初の実装スライスは次の順で進める。

1. `preview camera` という用語を UI / docs に固定する
2. `simulation/ui/preview/camera_state` を追加する
3. preview panel にだけ gizmo overlay を描く

この 3 ステップで、現在の camera controls の意味を確認できる状態を先に作り、その後で robot camera 4 面化に進む。
