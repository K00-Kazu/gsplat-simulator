# アーキテクチャ概要
- SimulationCore を単一の状態管理主体とし、UI・RenderWorker・Transport はすべて Core を介して接続する。
## UI
- ライブラリ：Qt(QOpenGLWidget)
- 実装言語：C++
- preview 表示
- 操作入力
- 状態表示
- デバッグオーバーレイ
- SimulationCore との IPC client
## SimulationCore
- ライブラリ：none
- 実装言語：Rust
- app state
- 時刻管理
- カメラ状態
- Config Loader
- transport
- フレーム生成要求の司令塔
- process supervision
## RenderWorker
- ライブラリ：gsplat
- 実装言語：Python
- Gaussian Splatting描画
- RGB / Depth / Segmentation など出力生成
- GPU資源管理
- offscreen render
## Transport/
- ライブラリ：zenoh
- 実装:Rust
- 外部制御API
- 画像配信
- メタデータ配信
## Shared schema / config
- ライブラリ：none
- 実装言語：Rust (crate)
- CameraSpec
- CameraPose
- RenderRequest
- FrameMetadata
- Config schema
- Topic naming
- versioning
---

# Process構成
## Process 1: UI(thread)
- Qt event loop
- viewport
- user input
- stats display (IPC receive thread)
## Process 2: SimulationCore
- thread 1: main/control thread
    - app state machine
    - command dispatch
    - shutdown orchestration
- thread 2: scheduler thread
    - simulation clock
    - render tick 生成
    - fps 制御
- thread 3: renderer IPC RX/TX thread
    - RenderWorker 通信
    - frame ready 受信
- thread 4: transport thread
    - zenoh publish
    - control command subscribe
- thread 5: frame routing thread
    - preview 用キュー
    - publish 用キュー
    - drop policy 実施
- thread 4&5は現状同一スレッドで実装予定だが将来分離予定
## Process 3: RenderWorker
- thread 1: command thread
    - request 受信
    - scene load
    - render order 制御
- thread 2: render thread
    - gsplat 呼び出し
    - offscreen rendering
    - GPU 実行
- thread 3: output thread
    - frame を CPU 側へ取り出し
    - Core に返送
- thread 2&3は現状同一スレッドで実装予定だが将来分離予定
---

# データフロー
## 制御フロー
- UI → Core → RenderWorker
- UI → Core → Transport
- Transport → Core → RenderWorker (将来実装予定)
## 画像フロー
- RenderWorker → Core → UI
- RenderWorker → Core → Transport(zenoh publish)
# メッセージ境界
## UI → Core(IPC / TCP localhost)
- LoadScene(scene_path)
- SetViewCameraPose(pose)
- SetOutputResolution(w, h)
- SetFoV(fov_y)
- Play
- Pause
- StepOnce
- Shutdown
## Core → UI(IPC / TCP localhost)
- AppState
- Stats
- PreviewFrameReady(frame_id)
- Error
- SceneInfo
## Core → RenderWorker(IPC / TCP localhost)
- LoadScene
- ConfigureCamera
- RenderFrame
- Shutdown
## RenderWorker → Core(IPC / TCP localhost)
- SceneLoaded
- FrameReady
- Error
- RendererStats
## Core → Transport(IPC / TCP localhost)
- FrameMetadata
- FramePayload