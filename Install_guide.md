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
| CMake | 4.3.1 |
---

# 2. リポジトリ取得
```bash
git clone <repository-url>
cd project-root
```
---

# 3. Python 環境構築 (RenderWorker)
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
- pytorchのinstallを実施後、下記の項目を実行
```bash
pip install -r requirements.txt
```
- Windows:
```bash
pip install --no-cache-dir gsplat --index-url https://docs.gsplat.studio/whl/pt24cu124
```
- 実行確認(CUDA利用を想定)
```bash
python -c "import torch; print(torch.cuda.is_available())"
```
`True` が返れば正常です。
---

# 4. Rust 環境構築
```bash
rustup toolchain install 1.94.1
rustup default 1.94.1
```
---

# 5. Qt 設定
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

# 6. Windows: zenoh-c / zenoh-cpp を third_party へ配置
`apps/ui` の `zenoh` 連携は、リポジトリ内の以下の配置を優先して参照します。

```text
third_party/zenoh/windows/zenohc
third_party/zenoh/windows/zenohcxx
```

`zenoh-cpp` は header-only ですが、`zenoh-c` バックエンドが必要です。
このため、Windows では `zenoh-c` と `zenoh-cpp` をセットで配置してください。

## 6.1 zenoh-c を配置
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

## 6.2 zenoh-cpp を配置
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

## 6.3 動作確認
`apps/ui` は `ui-debug` preset で `zenoh=ON` のビルドができます。

Windows の `cmd` では、必要なら configure 時に `QT_ROOT` を付けて実行します。

```bash
set QT_ROOT=C:\Qt\6.11.0\msvc2022_64&& cmake --preset ui-debug
cmake --build --preset ui-debug
```

生成物:

```text
build/cmake/ui-debug/apps/ui/Debug/gsplat_ui.exe
```

`zenoh-c` / `zenoh-cpp` を再配置した場合は、必要に応じて `build/cmake/ui-debug` を削除してから configure し直してください。
---

# 7. ビルド
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

# 8. 実行
```bash
python run.py dev
```
起動されるプロセス:
- UI
- SimulationCore
- RenderWorker
---

# 9. サンプルデータ
サンプルモデルは以下に配置されています。
```
assets/sample_models/
```

---
