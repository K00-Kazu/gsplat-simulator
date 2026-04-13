# Install Guide - Docker版 (Ubuntu対応)

本ドキュメントでは、Docker環境を使用してUbuntu上でgsplat-simulatorを実行する方法を説明します。

---

## 1. 前提条件

### 必須環境
- Docker Engine 20.10以上
- NVIDIA Container Toolkit（CUDA対応のため）
- X11サーバー（GUIアプリケーション表示のため）

### ホストシステム要件
| 項目 | 要件 |
|------|------|
| OS | Ubuntu 20.04 / 22.04 / 24.04（ネイティブまたはWSL2） |
| GPU | NVIDIA GPU（CUDA対応） |
| GPU Driver | 535以上推奨 |
| Docker | 20.10以上 |
| Docker Compose | 2.0以上（オプション） |

### WSL2環境での注意事項

WSL2で実行する場合は、以下の追加設定が必要です：
- Windows側にNVIDIA GPUドライバをインストール（WSL2用）
- Docker Desktop for Windows、またはWSL2内でDockerをインストール
- systemdの有効化（Ubuntu 22.04以降のWSL2の場合）

---

## 2. WSL2環境での追加設定

WSL2で実行している場合は、このセクションを先に確認してください。

### 2.1 systemdの有効化（Ubuntu 22.04以降のWSL2）

```bash
# systemdが有効か確認
systemctl --version

# 有効でない場合、/etc/wsl.confを編集
sudo tee /etc/wsl.conf <<EOF
[boot]
systemd=true
EOF

# WSLを再起動（Windows PowerShellで実行）
# wsl --shutdown
# その後、WSLを再起動
```

### 2.2 Docker Desktop for Windowsを使用する場合

**推奨**: WSL2環境では、Docker Desktop for Windowsの使用が最も簡単です。

1. [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)をインストール
2. Settings > Resources > WSL Integration で使用するWSLディストリビューションを有効化
3. Docker Desktop for WindowsにはNVIDIA Container Toolkitが組み込まれているため、追加インストール不要

**動作確認**:
```bash
# WSL2内で実行
docker --version
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 2.3 WSL2内でDockerをネイティブインストールする場合

Docker Desktop for Windowsを使わず、WSL2内でDockerを直接管理する場合：

```bash
# 古いDockerパッケージを削除
sudo apt-get remove docker docker-engine docker.io containerd runc

# 必要なパッケージをインストール
sudo apt-get update
sudo apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    lsb-release

# Docker公式GPGキーの追加
sudo mkdir -p /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Dockerリポジトリの追加
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Dockerのインストール
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# systemdが有効な場合
sudo systemctl start docker
sudo systemctl enable docker

# systemdが無効な場合（手動起動）
sudo dockerd > /dev/null 2>&1 &

# ユーザーをdockerグループに追加（sudoなしでdockerコマンドを実行可能に）
sudo usermod -aG docker $USER
newgrp docker

# 動作確認
docker --version
docker ps
```

---

## 3. NVIDIA Container Toolkitのインストール

GPUをDockerコンテナで利用するため、NVIDIA Container Toolkitが必要です。

**注意**: Docker Desktop for Windowsを使用している場合、このセクションはスキップしてください（既に組み込まれています）。

### 最新の公式手順（ネイティブLinux / WSL2でDockerをネイティブインストールした場合）

```bash
# リポジトリの設定
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg \
  && curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# パッケージリストの更新
sudo apt-get update

# インストール
sudo apt-get install -y nvidia-container-toolkit

# Dockerランタイムの設定
sudo nvidia-ctk runtime configure --runtime=docker

# Dockerデーモンの再起動
# systemdが有効な場合
sudo systemctl restart docker

# systemdが無効な場合（WSL2等）
# Dockerプロセスを再起動
sudo pkill dockerd
sudo dockerd > /dev/null 2>&1 &

# 動作確認
docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### トラブルシューティング: リポジトリエラーが発生する場合

`apt-get update`実行時に以下のようなエラーが出る場合：
```
E: Type '<!doctype' is not known on line 1 in source list
```

これはHTMLページが返ってきている（404エラー等）ことを示します。以下の代替手順を試してください。

#### 代替手順1: 手動でのリポジトリ設定

```bash
# 既存の問題のあるリストファイルを削除
sudo rm -f /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Ubuntu 22.04の場合
echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/deb/amd64 /" | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# Ubuntu 20.04の場合
# echo "deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://nvidia.github.io/libnvidia-container/stable/ubuntu20.04/amd64 /" | \
#     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

# GPGキーの追加
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

# 再度更新とインストール
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
```

#### 代替手順2: 直接debパッケージをインストール

```bash
# 最新版を確認: https://github.com/NVIDIA/nvidia-container-toolkit/releases
TOOLKIT_VERSION="1.16.2"  # 最新版に置き換え
ARCH="amd64"

wget https://github.com/NVIDIA/nvidia-container-toolkit/releases/download/v${TOOLKIT_VERSION}/nvidia-container-toolkit_${TOOLKIT_VERSION}_${ARCH}.deb
sudo dpkg -i nvidia-container-toolkit_${TOOLKIT_VERSION}_${ARCH}.deb

# 依存関係の解決
sudo apt-get install -f
```

---

GUIアプリケーション（Qt6 UI）を表示するため、X11転送を設定します。

### ネイティブLinuxの場合

```bash
# X11接続を許可
xhost +local:docker

# または、より安全な設定
xhost +local:$(whoami)
```

### WSL2の場合

WSL2では、Windows側でX11サーバーを起動する必要があります。

#### 方法1: WSLgを使用（Windows 11推奨）

Windows 11では、WSLgが自動的にGUIをサポートします。追加設定は不要です。

```bash
# 確認
echo $DISPLAY
# :0 または類似の値が表示されればOK
```

#### 方法2: VcXsrvまたはX410を使用

1. Windows側で[VcXsrv](https://sourceforge.net/projects/vcxsrv/)または[X410](https://x410.dev/)をインストール
2. X11サーバーを起動（アクセス制御を無効化）
3. WSL2側で環境変数を設定

```bash
# WSL2のIPアドレスを取得
export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0

# または、直接指定
export DISPLAY=:0

# .bashrcに追加して永続化
echo 'export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk "{print \$2}"):0' >> ~/.bashrc
```

**注意**: セキュリティ上、`xhost +local:docker`は開発環境でのみ使用してください。

---

## 5. Dockerイメージのビルド

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

### ビルド時のトラブルシューティング

#### Qt6のインストールに失敗する場合

Dockerfileでは`aqtinstall`を使用してQt6をインストールしています。ネットワークの問題でインストールに失敗する場合は、手動でQt6をインストールする必要があります。

**使用するQtバージョン**:
- Dockerfile内でQt 6.6.0 LTS（推奨）→ 6.6.0 → 6.5.3の順でフォールバック
- Install_guide.mdで指定されている6.11.0は、aqtinstallで利用できない場合があります

**利用可能なQtバージョンを確認**:
```bash
# ホスト側で実行
pip install aqtinstall
python -m aqt list-qt linux desktop
```

**対処方法1: 別のQtバージョンを試す**
Dockerfileの該当箇所を編集：
```dockerfile
# Qt 6.5.3 LTSを使用する例
RUN python3 -m pip install --upgrade pip && \
    pip3 install aqtinstall && \
    python3 -m aqt install-qt linux desktop 6.5.3 gcc_64 -O /opt/Qt --modules qtcharts qtnetworkauth
```

**対処方法2: ホスト側のQt6をマウント**
1. ホスト側でQt6をダウンロード・インストール
2. Dockerコンテナにボリュームマウントで共有
3. 環境変数`QT_ROOT`を適切に設定

```bash
# 例: ホスト側のQt6をマウント
docker run --gpus all \
    -v /opt/Qt:/opt/Qt \
    -e QT_ROOT=/opt/Qt/6.6.0/gcc_64 \
    ...
```

**対処方法3: Qt6をシステムパッケージからインストール**
Ubuntu 22.04では、Qt 6.2がaptで利用可能です（ただし古いバージョン）：
```dockerfile
# Dockerfileに追加
RUN apt-get update && apt-get install -y \
    qt6-base-dev \
    qt6-tools-dev \
    && rm -rf /var/lib/apt/lists/*
```

---

## 6. コンテナの起動

### docker-composeを使用する場合（推奨）

プロジェクトルートに`docker-compose.yml`が用意されています。

**重要**: 環境変数（`QT_ROOT`、`ZENOHC_ROOT`、`ZENOHCXX_ROOT`）はDockerfile内で自動設定されているため、手動での設定は不要です。

起動:
```bash
# Docker Compose V2を使用（推奨）
docker compose up -d
docker compose exec gsplat-simulator bash

# または、Docker Compose V1
docker-compose up -d
docker-compose exec gsplat-simulator bash
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

**注意**: 環境変数はDockerfileで自動設定されているため、`-e`オプションで追加指定する必要はありません。

---

## 7. プロジェクトのビルド

コンテナ内で以下の手順を実行します。

### 7.1 Python環境のセットアップ

**重要**: `requirements.txt`にgsplatが含まれていますが、インストール順序が重要です。以下の手順で実行してください。

```bash
cd /workspace/apps/render

# 仮想環境の作成
python3 -m venv .venv

# 仮想環境の有効化
source .venv/bin/activate

# pipのアップグレード
pip install --upgrade pip setuptools wheel

# PyTorchのインストール（CUDA 12.4対応）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124

# その他の依存関係をインストール
pip install -r requirements.txt

# gsplatをインストール（requirements.txtの前に実行）
pip install --no-cache-dir gsplat==1.5.3 --extra-index-url https://docs.gsplat.studio/whl/pt24cu124

# CUDA動作確認
python -c "import torch; print('CUDA available:', torch.cuda.is_available())"
python -c "import gsplat; print('gsplat version:', gsplat.__version__)"
```

**インストール順序の説明**:
1. **PyTorch**: まずPyTorchをインストール（gsplatの基盤）
2. **jaxtyping, ninja**: gsplatが依存するパッケージ（ninjaはビルドツール）
3. **gsplat**: `requirements.txt`より前にインストール（競合を回避）
   - **重要**: `--extra-index-url`を使用（`--index-url`ではない）してデフォルトのPyPIも検索可能にする
4. **requirements.txt**: その他の依存関係（gsplatは既にインストール済みなので問題なし）

両方の`print`文で正しい結果が返れば成功です。

#### トラブルシューティング: 依存関係の競合エラー

`ERROR: ResolutionImpossible: ... depends on jaxtyping`のようなエラーが出る場合：

**方法1: requirements.txtからgsplatを一時的に除外**

```bash
# gsplat以外をインストール
grep -v "^gsplat" requirements.txt > requirements_no_gsplat.txt
pip install -r requirements_no_gsplat.txt

# gsplatを手動でインストール
pip install --no-cache-dir gsplat==1.5.3 --extra-index-url https://docs.gsplat.studio/whl/pt24cu124
```

**方法2: 仮想環境をクリーンアップして再作成**

```bash
# 仮想環境をクリーンアップ
deactivate
rm -rf .venv
python3 -m venv .venv
source .venv/bin/activate

# 依存関係を段階的にインストール
pip install --upgrade pip setuptools wheel
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
pip install jaxtyping ninja
pip install --no-cache-dir gsplat==1.5.3 --extra-index-url https://docs.gsplat.studio/whl/pt24cu124

# gsplat以外の依存関係をインストール
grep -v "^gsplat" requirements.txt | xargs pip install
```

**`--index-url` vs `--extra-index-url`の違い**:
- `--index-url`: 指定したインデックスのみを検索（デフォルトのPyPIは無効）
- `--extra-index-url`: デフォルトのPyPIに加えて、指定したインデックスも検索

gsplatは独自のビルド済みwheelを提供していますが、依存パッケージ（ninja等）はデフォルトのPyPIから取得する必要があるため、`--extra-index-url`を使用します。

**方法3: requirements.txtを修正する（apps以下の修正が必要）**

`apps/render/requirements.txt`からgsplatの行を削除し、別途インストールする方法もあります。ただし、この場合は[セクション11](Install_guide_docker.md#11-apps以下のコード修正について)に従って記録してください。

### 7.2 Rustコアのビルド

```bash
cd /workspace

# Rustプロジェクトのビルド
cargo build --release
```

### 7.3 Qt UIのビルド

DockerイメージにはCMake 3.29以降が含まれており、CMakeプリセットが利用可能です。

**環境変数は自動設定済み**: Dockerfileで環境変数が自動的に設定されているため、手動設定は不要です。

```bash
# 環境変数を確認（自動設定されているはず）
echo "QT_ROOT: $QT_ROOT"
echo "ZENOHC_ROOT: $ZENOHC_ROOT"
echo "ZENOHCXX_ROOT: $ZENOHCXX_ROOT"

# Qtのインストールディレクトリを確認
ls -la /opt/Qt/
```

#### 方法1: CMakeプリセットを使用（推奨）

```bash
cd /workspace

# 利用可能なプリセットを確認
cmake --list-presets

# Releaseビルド（zenoh有効）
cmake --preset ui-linux-release
cmake --build --preset ui-linux-release

# または、Debugビルド
cmake --preset ui-linux-debug
cmake --build --preset ui-linux-debug
```

#### 方法2: 手動設定

```bash
cd /workspace

# 手動設定でCMakeを実行（zenoh有効）
cmake -S apps/ui -B build/ui \
    -DCMAKE_BUILD_TYPE=Release \
    -DGSPLAT_UI_ENABLE_ZENOH=ON \
    -Dzenohc_DIR=${ZENOHC_ROOT}/lib/cmake/zenohc

# ビルド
cmake --build build/ui --config Release
```

**zenohを無効にする場合**（テスト目的など）：
```bash
cmake -S apps/ui -B build/ui \
    -DCMAKE_BUILD_TYPE=Release \
    -DGSPLAT_UI_ENABLE_ZENOH=OFF

cmake --build build/ui --config Release
```

### ビルド成果物

- **Rust**: `target/release/`
- **UI**: `build/ui/apps/ui/gsplat_ui`（CMakeプリセット使用時）
- **Render**: `apps/render/main.py`（Python仮想環境内で実行）

**注意**: UIバイナリの場所は、ビルド方法によって異なります：
- CMakeプリセット（`cmake --preset ui-linux-release`）: `build/ui/apps/ui/gsplat_ui`
- 手動設定（`cmake -S apps/ui -B build/ui`）: `build/ui/gsplat_ui`

### トラブルシューティング: CMake関連

#### CMakeのバージョンが古い場合

CMake 3.25未満の場合、CMake Presets version 6がサポートされていません：

```bash
# CMakeバージョンを確認
cmake --version

# バージョンが3.25未満の場合、Dockerイメージを再ビルド
# Dockerfileには最新のCMakeがインストールされる設定が含まれています
docker build --no-cache -t gsplat-simulator:latest .
```

#### Qt6が見つからない

**エラーメッセージ**:
```
Could not find a package configuration file provided by "Qt6"
```

**原因**: `QT_ROOT`環境変数が設定されていないか、Qt6がインストールされていない

**対処法**:

1. **環境変数を確認・設定**
```bash
# QT_ROOT環境変数を確認
echo $QT_ROOT

# Qtのインストールディレクトリを確認
ls -la /opt/Qt/

# インストールされているQtバージョンを確認
ls /opt/Qt/ | grep -E "^6\."

# 通常は自動設定されているはず
# 設定されていない場合のみ手動で設定（古いイメージの場合）
export QT_ROOT=/opt/Qt/6.6.0/gcc_64
export ZENOHC_ROOT=/opt/zenoh/zenohc
export ZENOHCXX_ROOT=/opt/zenoh/zenohcxx
```

**注意**: 最新のDockerイメージを使用している場合、環境変数は自動設定されているため、上記の手動設定は不要です。

2. **Qt6がインストールされていない場合**

Dockerイメージが正しくビルドされていない可能性があります：
```bash
# ホスト側でイメージを再ビルド
docker build --no-cache -t gsplat-simulator:latest .

# または、コンテナ内でQt6を手動インストール
pip3 install aqtinstall
python3 -m aqt install-qt linux desktop 6.6.0 gcc_64 -O /opt/Qt
```

3. **CMakeに明示的にQt6のパスを渡す**
```bash
cmake -S apps/ui -B build/ui \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_PREFIX_PATH=${QT_ROOT} \
    -DGSPLAT_UI_ENABLE_ZENOH=ON \
    -Dzenohc_DIR=${ZENOHC_ROOT}/lib/cmake/zenohc

cmake --build build/ui
```

---

## 8. アプリケーションの実行

### 8.1 統合実行 - dev_run_app.py（推奨）

**tmuxを使用したマルチターミナル起動**

プロジェクトルートに`dev_run_app.py`が用意されており、全コンポーネントをtmuxセッション内で起動できます。

```bash
# コンテナ内で実行
cd /workspace

# 全コンポーネントを起動（tmuxセッション内）
python dev_run_app.py start

# または
./dev_run_app.py start
```

**tmux操作方法**:
- `Ctrl+b, 0/1/2` - ウィンドウ切り替え（0:UI, 1:RenderWorker, 2:SimulationCore）
- `Ctrl+b, d` - tmuxセッションからデタッチ（バックグラウンドで実行継続）
- `Ctrl+b, :kill-session` - セッション終了

**その他のコマンド**:
```bash
# セッションにアタッチ（デタッチ後に再接続）
python dev_run_app.py attach

# セッション状態を確認
python dev_run_app.py status

# セッションを停止
python dev_run_app.py stop
```

**前提条件**:
- UIがビルド済み（`build/ui/gsplat_ui`が存在）
- Python仮想環境が作成済み（`apps/render/.venv`が存在）
- Rustプロジェクトがビルド済み（オプション）

### 8.2 個別実行

各コンポーネントを別々のターミナルで手動起動する場合：

```bash
# ターミナル1: UI
cd /workspace
./build/ui/apps/ui/gsplat_ui  # CMakeプリセット使用時
# または ./build/ui/gsplat_ui  # 手動設定の場合

# ターミナル2: Render Worker（別のターミナルで）
docker compose exec gsplat-simulator bash
cd /workspace/apps/render
source .venv/bin/activate
python main.py

# ターミナル3: Simulation Core（別のターミナルで）
docker compose exec gsplat-simulator bash
cd /workspace
./target/release/simulation_core  # 実際のバイナリ名に置き換え
```

### X11転送の設定（GUIを表示するため）

UIを起動する前に、X11転送が正しく設定されていることを確認してください。

#### Windows 11（WSLg使用）

```bash
# 自動的にサポートされています
echo $DISPLAY  # :0 や :1 と表示されればOK
```

#### Windows 10またはWSLgを使わない場合

```bash
# Windows側でVcXsrvまたはX410を起動

# WSL2側でDISPLAY変数を設定
export DISPLAY=$(cat /etc/resolv.conf | grep nameserver | awk '{print $2}'):0

# xhostでアクセス許可
xhost +local:docker
```

#### 動作確認

```bash
# X11が機能しているか確認
xeyes  # ウィンドウが表示されればOK
```

---

## 9. トラブルシューティング

### 9.1 GUIが表示されない

**原因**: X11転送の設定不足

**対処法**:
```bash
# ホスト側
xhost +local:docker

# コンテナ起動時にDISPLAY変数を確認
echo $DISPLAY
```

### 9.2 CUDAが利用できない

**原因**: NVIDIA Container Toolkitの設定不足、またはGPUドライバの問題

**対処法**:
```bash
# ホスト側でGPUを確認
nvidia-smi

# Dockerでnvidia-runtimeを使用
docker run --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
```

### 9.3 zenohのビルドエラー

**原因**: zenoh-cまたはzenoh-cppのビルド失敗

**対処法**:
Dockerfileの該当セクションを確認し、ビルドログを調査してください。必要に応じて手動でビルドしてコンテナにコピーします。

```bash
# ホスト側でビルド
cd /tmp
git clone --branch 1.8.0 https://github.com/eclipse-zenoh/zenoh-c.git
cd zenoh-c
# ビルド手順...

# コンテナにコピー
docker cp /path/to/built/zenoh gsplat-sim:/opt/zenoh/
```

---

## 10. 開発時のTips

### 10.1 コードの変更を即座に反映

ボリュームマウントを使用しているため、ホスト側でコードを編集すればコンテナ内でも反映されます。

### 10.2 コンテナの永続化

開発用にコンテナを永続化する場合：

```bash
docker run -d \
    --gpus all \
    --name gsplat-sim-dev \
    -e DISPLAY=$DISPLAY \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v $(pwd):/workspace \
    gsplat-simulator:latest \
    sleep infinity

# コンテナに入る
docker exec -it gsplat-sim-dev bash
```

### 10.3 Pythonパッケージの追加

```bash
# コンテナ内
cd /workspace/apps/render
source .venv/bin/activate
pip install <package-name>
pip freeze > requirements.txt  # 更新を保存
```

---

## 11. apps以下のコード修正について

**基本方針**: apps以下のコードは修正しない

ただし、以下のケースで修正が必要になる可能性があります：

### 11.1 パス設定の調整

Docker環境では絶対パスが異なる場合があります。設定ファイルやコード内でハードコードされたパスがある場合、環境変数を使用するように変更が推奨されます。

**例**:
```python
# 修正前
config_path = "C:\\path\\to\\config.json"

# 修正後
import os
config_path = os.getenv("CONFIG_PATH", "/workspace/config/config.json")
```

### 11.2 zenohの設定

Docker環境（同一コンテナ内で複数コンポーネントを実行）では、ポート競合を避けるためにzenoh設定を調整済みです。

`config/transport.dev.json`は以下のように設定されています：

```json
{
  "zenoh": {
    "mode": "peer",
    "listen": {
      "endpoints": ["tcp/0.0.0.0:0"]  // ランダムポートを使用
    },
    "scouting": {
      "multicast": {
        "enabled": true  // マルチキャストで自動探索
      }
    }
  }
}
```

**設定のポイント**:
- `tcp/0.0.0.0:0`: 各コンポーネントがランダムな空きポートでlistenします（ポート競合を回避）
- `multicast.enabled: true`: マルチキャストを有効にして、コンポーネント間で自動的に相互発見します
- Docker環境（同一ホスト内）では、マルチキャストが正常に機能します

**トラブルシューティング**: ポート競合エラーが出る場合

```
ZError: Can not create a new TCP listener bound to tcp/127.0.0.1:7447: Address already in use
```

このエラーは、複数のコンポーネントが同じポートを使おうとしています。上記の設定を適用してください。

**以前の設定（ポート固定、非推奨）**:
```json
{
  "zenoh": {
    "mode": "peer",
    "connect": {
      "endpoints": ["tcp/127.0.0.1:7447"]
    },
    "listen": {
      "endpoints": ["tcp/127.0.0.1:7447"]  // すべてが同じポートを使用 → 競合
    }
  }
}
```

---

## 12. 本番環境への展開

本Docker環境は開発用です。本番環境では以下を検討してください：

1. マルチステージビルドの最適化（不要なビルドツールの除去）
2. 実行専用ユーザーの作成（rootで実行しない）
3. セキュリティスキャン（Trivy等）
4. イメージサイズの削減

---

## 参考リンク

- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
- [Qt for Linux](https://doc.qt.io/qt-6/linux.html)
- [zenoh Documentation](https://zenoh.io/docs/)
- [gsplat Documentation](https://docs.gsplat.studio/)
