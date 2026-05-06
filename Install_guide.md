# Install Guide (開発環境構築手順)
本ドキュメントでは、本プロジェクトの開発環境を Windows / Ubuntu で共通の手順により構築する方法を説明します。

---
# 1. 前提条件
## 必須バージョン
以下のバージョンを使用して開発をしています。

| 項目 | バージョン |
|------|-----------|
| Python | 3.10 |
| PyTorch | 2.4.1 |
| gsplat | 1.5.3 |
| CUDA Toolkit | 12.8 |
| Rust | 1.94.1 |
| Qt | 6.11.0 |
| zenoh / zenoh-c / zenoh-cpp | 1.8.0 |
| C++ | C++17 |
| Visual Studio (Windows) | 2022 v17.14.21 |
| CMake | 3.29以上推奨 |

### Ubuntu/WSL2利用時の追加項目
- Docker Engine 20.10以上
- Docker Compose 2.0以上
- X11サーバー（GUIアプリケーション表示のため）

---
# 2. リポジトリ取得
```bash
git clone <repository-url>
cd project-root
```
---
## 3. Dockerイメージのビルド(Docker利用時のみ)

プロジェクトルートディレクトリで以下を実行します。

```bash
cd /path/to/gsplat-simulator

# Dockerイメージのビルド
docker build -t gsplat-simulator:latest .
```

**注意**: 初回ビルドは30分〜1時間程度かかる場合があります。Qt6とzenohのビルドに時間を要します。

### ビルド時の環境変数自動設定について

Dockerfileでは以下の環境変数が**自動的に設定**されます：

| 環境変数 | 設定値 | 説明 |
|---------|--------|------|
| `QT_ROOT` | `/opt/Qt/6.6.0/gcc_64` | Qt6のルートディレクトリ |
| `ZENOHC_ROOT` | `/opt/zenoh/zenohc` | zenoh-cのインストールディレクトリ |
| `ZENOHCXX_ROOT` | `/opt/zenoh/zenohcxx` | zenoh-cppのインストールディレクトリ |
| `PATH` | Qt6のbinディレクトリを追加 | Qt6コマンドを直接実行可能 |
| `LD_LIBRARY_PATH` | Qt6とzenohのlibディレクトリ | 動的ライブラリの検索パス |

これらの環境変数は：
- `ENV`命令でDockerイメージに埋め込まれます（非対話型シェルで有効）
- `/etc/profile.d/qt-env.sh`に保存され、ログインシェルで自動読み込みされます
- `/etc/bash.bashrc`に追加され、対話型シェルでも自動読み込みされます

そのため、コンテナ起動後に手動で環境変数を設定する必要はありません。

---
# 4. Python 環境構築 (RenderWorker)
```bash
cd apps/render
python -m venv .venv
```
### 仮想環境有効化
#### Windows
```bash
.venv\Scripts\activate
```
#### Ubuntu
```bash
source .venv/bin/activate
```
### 依存インストール
PyTorchのインストールを実施後、下記の項目を実行します。

**重要**: インストール順序を守ってください（依存関係の競合を回避）

```bash
# 1. PyTorchインストール後、gsplatの依存関係を先にインストール
pip install jaxtyping typing-extensions ninja

# 2. gsplatをインストール（requirements.txtより前）
# 注意: --extra-index-url を使用（--index-url ではない）
pip install --no-cache-dir gsplat==1.5.3 --extra-index-url https://docs.gsplat.studio/whl/pt24cu124

# 3. その他の依存関係
pip install -r requirements.txt
```

**`--index-url` vs `--extra-index-url`の違い**:
- `--index-url`: 指定したインデックス**のみ**を検索（デフォルトのPyPI無効）→ ninjaが見つからずエラー
- `--extra-index-url`: デフォルトのPyPI**に加えて**指定したインデックスも検索 → 推奨

もし依存関係の競合エラーが出る場合は、以下の順序を試してください：
```bash
# gsplat以外をインストール
grep -v "^gsplat" requirements.txt | xargs pip install

# gsplatを個別にインストール
pip install --no-cache-dir gsplat==1.5.3 --extra-index-url https://docs.gsplat.studio/whl/pt24cu124
```

- 実行確認(CUDA利用を想定)
```bash
python -c "import torch; print(torch.cuda.is_available())"
python -c "import gsplat; print(gsplat.__version__)"
```
`True` および `1.5.3` が返れば正常です。

---
# 5. Rust 環境構築
```bash
rustup toolchain install 1.94.1
rustup default 1.94.1
```
---
# 6. C++(Qt) 設定
## QT_ROOT 設定
- Qt は事前にダウンロードして配置してください。
- `QT_ROOT` は以下のどちらかを指す必要があります:
```
<Qt install path>
<Qt install path>/lib/cmake/Qt6
```
### Windows
QT_ROOT：C:\Qt\6.11.0\msvc2022_64

### Ubuntu
```bash
export QT_ROOT=/opt/Qt/6.x.x/gcc_64
```
---
# 7. Windows: zenoh-c / zenoh-cpp を third_party へ配置
`apps/ui` の `zenoh` 連携は、リポジトリ内の以下の配置を優先して参照します。

```text
third_party/zenoh/windows/zenohc
third_party/zenoh/windows/zenohcxx
```

`zenoh-cpp` は header-only ですが、`zenoh-c` バックエンドが必要です。
このため、Windows では `zenoh-c` と `zenoh-cpp` をセットで配置してください。

## 7.1 zenoh-c を配置
Visual Studio 2022 の Developer Command Prompt もしくは通常の `cmd` で、リポジトリルートから実行します。

```bash
git clone --branch 1.8.0 https://github.com/eclipse-zenoh/zenoh-c.git build/vendor/zenoh-c-src
cmake -S build/vendor/zenoh-c-src -B build/vendor/zenoh-c-build -G "Visual Studio 17 2022" -A x64 -DCMAKE_INSTALL_PREFIX=%CD%/third_party/zenoh/windows/zenohc
cmake --build build/vendor/zenoh-c-build --config Release --target install
```

配置後、最低限以下が存在することを確認してください。

```text
third_party/zenoh/windows/zenohc/include/zenoh.h
third_party/zenoh/windows/zenohc/lib/zenohc.dll.lib
third_party/zenoh/windows/zenohc/bin/zenohc.dll
```

## 7.2 zenoh-cpp を配置
`zenoh-cpp` の configure 時に `zenoh-c` を見つけられるよう、`zenohc_DIR` を渡します。

```bash
git clone --branch 1.8.0 https://github.com/eclipse-zenoh/zenoh-cpp.git build/vendor/zenoh-cpp-src
cmake -S build/vendor/zenoh-cpp-src -B build/vendor/zenoh-cpp-build -G "Visual Studio 17 2022" -A x64 -DZENOHCXX_ZENOHC=ON -DZENOHCXX_ZENOHPICO=OFF -Dzenohc_DIR=%CD%/third_party/zenoh/windows/zenohc/lib/cmake/zenohc -DCMAKE_INSTALL_PREFIX=%CD%/third_party/zenoh/windows/zenohcxx
cmake --build build/vendor/zenoh-cpp-build --config Release --target install
```

配置後、最低限以下が存在することを確認してください。

```text
third_party/zenoh/windows/zenohcxx/include/zenoh.hxx
```

## 7.3 動作確認
`apps/ui` は `ui-debug` / `ui-release` preset で `zenoh=ON` のビルドができます。

Windows の `cmd` では、必要なら configure 時に `QT_ROOT` を付けて実行します。

```bash
set QT_ROOT=C:\Qt\6.11.0\msvc2022_64&& cmake --preset ui-debug
cmake --build --preset ui-debug

set QT_ROOT=C:\Qt\6.11.0\msvc2022_64&& cmake --preset ui-release
cmake --build --preset ui-release
```

生成物:

```text
build/cmake/ui-debug/apps/ui/Debug/gsplat_ui.exe
build/cmake/ui-release/apps/ui/Release/gsplat_ui.exe
```

`zenoh-c` / `zenoh-cpp` を再配置した場合は、必要に応じて `build/cmake/ui-debug` / `build/cmake/ui-release` を削除してから configure し直してください。

---
# 8. ビルド
トップディレクトリで実行:
```bash
python run.py build
```

内部処理:
- Rust build (cargo)
- UI build (CMake)

`apps/ui` の `zenoh` 連携を有効化する場合は、事前に `third_party/zenoh/windows` へ `zenoh-c` / `zenoh-cpp` を配置してください。
UI 起動時には `zenoh` のスモークテストとして、セッションを開いて起動メッセージを publish します。

---
# 9. 実行

## Docker環境

- 起動
```bash
# Docker Compose V2を使用（推奨）
docker compose up -d
docker compose exec gsplat-simulator bash
```
- 実行
```bash
# コンテナ内で実行
cd /workspace
# tmuxセッション内で全コンポーネント（UI、SimulationCore、RenderWorker）が起動します。
python dev_run_app.py start
```

### docker runコマンドを使用する場合

```bash
docker run --rm -it \
    --gpus all \
    --name gsplat-sim \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $(pwd):/workspace \
    gsplat-simulator:latest
```

## ネイティブ環境（Windows）

各コンポーネントを個別に起動：

```bash
# ターミナル1: UI
cd apps/ui
build\Debug\gsplat_ui.exe

# ターミナル2: RenderWorker
cd apps\render
.venv\Scripts\activate
python main.py

# ターミナル3: SimulationCore
cargo run --release
```

---
# 10. サンプルデータ
サンプルモデルは以下に配置されています。
```
assets/sample_models/
```

---
# 11. UI ビルド

## CMakeプリセットを使用（Windows/Linux共通、推奨）

CMakePresets.jsonにはWindows向けとLinux向けの設定が含まれています。

```bash
# 利用可能なプリセットを確認
cmake --list-presets

# Windows: UI Debug
cmake --preset ui-debug
cmake --build --preset ui-debug

# Windows: UI Release
cmake --preset ui-release
cmake --build --preset ui-release

# Linux: UI Release
cmake --preset ui-linux-release
cmake --build --preset ui-linux-release

# Linux: UI Debug（zenoh有効）
cmake --preset ui-linux-debug
cmake --build --preset ui-linux-debug
```

## 手動設定（環境変数を使用）

プリセットを使わない場合は、以下のように環境変数を設定してビルドします。

### Windows (PowerShell)
```powershell
$env:QT_ROOT="C:\Qt\6.11.0\msvc2022_64"
$env:ZENOHC_ROOT="C:\path\to\zenohc"
$env:ZENOHCXX_ROOT="C:\path\to\zenohcxx"

cmake -S apps/ui -B build/ui -DGSPLAT_UI_ENABLE_ZENOH=ON
cmake --build build/ui --config Release
```

### Linux (Bash)
```bash
export QT_ROOT=/opt/Qt/6.7.0/gcc_64
export ZENOHC_ROOT=/path/to/zenohc
export ZENOHCXX_ROOT=/path/to/zenohcxx

cmake -S apps/ui -B build/ui \
    -DCMAKE_BUILD_TYPE=Release \
    -DGSPLAT_UI_ENABLE_ZENOH=ON
cmake --build build/ui --config Release
```

### zenohを無効にする場合
```bash
cmake -S apps/ui -B build/ui
cmake --build build/ui --config Release
```
