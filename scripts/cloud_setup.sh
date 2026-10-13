#!/usr/bin/env bash
set -euo pipefail
cd /workspace/fd
export UV_CACHE_DIR=/workspace/.cache/uv
export UV_PYTHON_INSTALL_DIR=/workspace/.python
export UV_PYTHON_BIN_DIR=/workspace/.local/bin
command -v uv >/dev/null
command -v ffmpeg >/dev/null
command -v ffprobe >/dev/null
uv python install 3.11
uv sync --locked --python /workspace/.python/cpython-3.11-linux-x86_64-gnu/bin/python3.11 \
  --extra ml --extra dev --extra build --extra hands
uv pip check --python .venv/bin/python
export GTAB_DATA_DIR="${GTAB_DATA_DIR:-/workspace/.local/share/guitar-tab-ai}"
export NUMBA_CACHE_DIR="${NUMBA_CACHE_DIR:-/workspace/.cache/numba}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-/workspace/.cache/matplotlib}"
mkdir -p "$GTAB_DATA_DIR" "$NUMBA_CACHE_DIR" "$MPLCONFIGDIR"
.venv/bin/python -c 'import PySide6, cv2, numpy, scipy, onnxruntime; from guitar_tab_ai.core.config import data_directory; from guitar_tab_ai.storage.database import Preferences; Preferences(data_directory()/"preferences.sqlite"); print("Development dependencies and writable project data verified")'
