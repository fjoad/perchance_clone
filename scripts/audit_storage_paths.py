from __future__ import annotations

import json
import os
from pathlib import Path

from f_only_env import configure_f_only_env, assert_f_only_env


CHECK_PATHS = [
    Path(r"F:\ollama"),
    Path(r"F:\ollama\models"),
    Path(r"F:\ollama\downloads"),
    Path(r"F:\huggingface"),
    Path(r"F:\huggingface\models"),
    Path(r"F:\huggingface\models\hub"),
    Path(r"F:\huggingface\models\assets"),
    Path(r"F:\huggingface\models\xet"),
    Path(r"F:\huggingface\models\torch"),
    Path(r"F:\huggingface\models\xdg_cache"),
    Path(r"F:\huggingface\models\pip_cache"),
    Path(r"F:\huggingface\models\cuda_cache"),
    Path(r"F:\huggingface\models\torch_extensions"),
    Path(r"F:\huggingface\models\torch_inductor"),
    Path(r"F:\huggingface\models\triton"),
    Path(r"F:\huggingface\models\matplotlib"),
    Path(r"F:\huggingface\models\numba_cache"),
    Path(r"F:\projects\perchance_clone\perchance_clone\runtime\codex_temp"),
    Path(r"F:\Programs\Ollama_0.21.0"),
    Path.home() / ".cache" / "huggingface",
    Path.home() / ".ollama" / "models",
    Path.home() / "AppData" / "Local" / "Programs" / "Ollama",
    Path.home() / "AppData" / "Local" / "Ollama",
    Path.home() / "AppData" / "Local" / "huggingface",
    Path.home() / "AppData" / "Roaming" / "huggingface",
    Path.home() / "AppData" / "Local" / "torch",
    Path.home() / ".torch",
]


def size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            pass
    return total


def main() -> int:
    configure_f_only_env()
    assert_f_only_env()

    rows = []
    for path in CHECK_PATHS:
        rows.append(
            {
                "path": str(path),
                "exists": path.exists(),
                "size_gb": round(size_bytes(path) / (1024**3), 3),
                "drive": path.drive,
                "is_risky_c_cache": path.drive.upper() == "C:" and path.exists(),
            }
        )

    result = {
        "env": {
            key: os.environ.get(key)
            for key in [
                "HF_HOME",
                "HF_HUB_CACHE",
                "HUGGINGFACE_HUB_CACHE",
                "TRANSFORMERS_CACHE",
                "HF_ASSETS_CACHE",
                "HF_XET_CACHE",
                "TORCH_HOME",
                "XDG_CACHE_HOME",
                "PIP_CACHE_DIR",
                "CUDA_CACHE_PATH",
                "TORCH_EXTENSIONS_DIR",
                "TORCHINDUCTOR_CACHE_DIR",
                "TRITON_CACHE_DIR",
                "MPLCONFIGDIR",
                "NUMBA_CACHE_DIR",
                "TMP",
                "TEMP",
                "TMPDIR",
                "SQLITE_TMPDIR",
                "OLLAMA_MODELS",
            ]
        },
        "paths": rows,
        "risky_c_paths": [row for row in rows if row["is_risky_c_cache"]],
    }
    print(json.dumps(result, indent=2))
    return 1 if result["risky_c_paths"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
