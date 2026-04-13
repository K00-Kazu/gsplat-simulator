# Ubuntu-based Docker environment for gsplat-simulator
# Multi-stage build for efficient image size

# Stage 1: Base image with CUDA support
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# Install system dependencies
RUN apt-get update && apt-get install -y \
    git \
    wget \
    curl \
    ca-certificates \
    gpg \
    build-essential \
    pkg-config \
    libssl-dev \
    python3.10 \
    python3.10-dev \
    python3.10-venv \
    python3-pip \
    ninja-build \
    # Development tools
    tmux \
    vim \
    less \
    # Qt6 dependencies
    libglib2.0-0 \
    libgl1-mesa-dev \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    libfontconfig1 \
    libfreetype6 \
    libx11-xcb1 \
    libdbus-1-3 \
    # For X11 forwarding
    x11-apps \
    && rm -rf /var/lib/apt/lists/*

# Install latest CMake from Kitware's official repository
RUN wget -O - https://apt.kitware.com/keys/kitware-archive-latest.asc 2>/dev/null | gpg --dearmor - | tee /usr/share/keyrings/kitware-archive-keyring.gpg >/dev/null \
    && echo "deb [signed-by=/usr/share/keyrings/kitware-archive-keyring.gpg] https://apt.kitware.com/ubuntu/ jammy main" | tee /etc/apt/sources.list.d/kitware.list >/dev/null \
    && apt-get update \
    && apt-get install -y cmake \
    && rm -rf /var/lib/apt/lists/* \
    && cmake --version

# Stage 2: Rust installation
FROM base AS rust-builder

# Install Rust
ENV RUSTUP_HOME=/usr/local/rustup
ENV CARGO_HOME=/usr/local/cargo
ENV PATH=/usr/local/cargo/bin:$PATH

RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --default-toolchain 1.94.1
RUN rustup default 1.94.1

# Stage 3: Qt6 installation
FROM base AS qt-installer

WORKDIR /tmp/qt-install

# Install Qt6 using aqtinstall
# Note: Qt 6.11.0 may not be available, try 6.6.0 LTS or check available versions
RUN python3 -m pip install --upgrade pip && \
    pip3 install aqtinstall && \
    python3 -m aqt list-qt linux desktop --arch 6.6.0 || true && \
    python3 -m aqt install-qt linux desktop 6.6.0 gcc_64 -O /opt/Qt --modules qtcharts qtnetworkauth || \
    (echo "Qt 6.6.0 failed, trying 6.6.0" && \
     python3 -m aqt install-qt linux desktop 6.6.0 gcc_64 -O /opt/Qt --modules qtcharts qtnetworkauth) || \
    (echo "Qt 6.6.0 failed, trying 6.5.3" && \
     python3 -m aqt install-qt linux desktop 6.5.3 gcc_64 -O /opt/Qt --modules qtcharts qtnetworkauth)

# Stage 4: Build zenoh dependencies
FROM rust-builder AS zenoh-builder

WORKDIR /tmp/zenoh-build

# Install zenoh-c
RUN git clone --branch 1.8.0 --depth 1 https://github.com/eclipse-zenoh/zenoh-c.git zenoh-c-src && \
    cmake -S zenoh-c-src -B zenoh-c-build \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/opt/zenoh/zenohc && \
    cmake --build zenoh-c-build --config Release --target install

# Install zenoh-cpp
RUN git clone --branch 1.8.0 --depth 1 https://github.com/eclipse-zenoh/zenoh-cpp.git zenoh-cpp-src && \
    cmake -S zenoh-cpp-src -B zenoh-cpp-build \
    -DCMAKE_BUILD_TYPE=Release \
    -DZENOHCXX_ZENOHC=ON \
    -DZENOHCXX_ZENOHPICO=OFF \
    -Dzenohc_DIR=/opt/zenoh/zenohc/lib/cmake/zenohc \
    -DCMAKE_INSTALL_PREFIX=/opt/zenoh/zenohcxx && \
    cmake --build zenoh-cpp-build --config Release --target install

# Stage 5: Final development image
FROM rust-builder AS development

# Copy Qt6 from qt-installer stage
COPY --from=qt-installer /opt/Qt /opt/Qt

# Copy zenoh from zenoh-builder stage
COPY --from=zenoh-builder /opt/zenoh /opt/zenoh

# Detect Qt version and set environment variables
# Try to find the installed Qt version directory
RUN QT_VERSION=$(ls /opt/Qt | grep -E '^6\.[0-9]+\.[0-9]+$' | sort -V | tail -n1) && \
    echo "export QT_ROOT=/opt/Qt/${QT_VERSION}/gcc_64" >> /etc/profile.d/qt-env.sh && \
    echo "export ZENOHC_ROOT=/opt/zenoh/zenohc" >> /etc/profile.d/qt-env.sh && \
    echo "export ZENOHCXX_ROOT=/opt/zenoh/zenohcxx" >> /etc/profile.d/qt-env.sh && \
    echo "export PATH=/opt/Qt/${QT_VERSION}/gcc_64/bin:\$PATH" >> /etc/profile.d/qt-env.sh && \
    echo "export LD_LIBRARY_PATH=/opt/Qt/${QT_VERSION}/gcc_64/lib:/opt/zenoh/zenohc/lib:\$LD_LIBRARY_PATH" >> /etc/profile.d/qt-env.sh && \
    echo "export QT_PLUGIN_PATH=/opt/Qt/${QT_VERSION}/gcc_64/plugins" >> /etc/profile.d/qt-env.sh && \
    echo "export QT_QPA_PLATFORM_PLUGIN_PATH=/opt/Qt/${QT_VERSION}/gcc_64/plugins/platforms" >> /etc/profile.d/qt-env.sh && \
    chmod +x /etc/profile.d/qt-env.sh && \
    echo "source /etc/profile.d/qt-env.sh" >> /etc/bash.bashrc

# Set environment variables (Docker ENV for non-interactive shells)
ENV QT_ROOT=/opt/Qt/6.6.0/gcc_64
ENV ZENOHC_ROOT=/opt/zenoh/zenohc
ENV ZENOHCXX_ROOT=/opt/zenoh/zenohcxx
ENV PATH=/opt/Qt/6.6.0/gcc_64/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/Qt/6.6.0/gcc_64/lib:/opt/zenoh/zenohc/lib:${LD_LIBRARY_PATH}
ENV QT_PLUGIN_PATH=/opt/Qt/6.6.0/gcc_64/plugins
ENV QT_QPA_PLATFORM_PLUGIN_PATH=/opt/Qt/6.6.0/gcc_64/plugins/platforms

# Create workspace
WORKDIR /workspace
ENV WORKDIR=/workspace

# Install Python dependencies globally (to be overridden by project venv)
RUN python3 -m pip install --upgrade pip setuptools wheel

# Expose display for X11 forwarding
ENV DISPLAY=:0

# Default command
CMD ["/bin/bash"]
