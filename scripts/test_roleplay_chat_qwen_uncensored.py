from __future__ import annotations

import sys

import test_roleplay_chat as chat

from app.config import settings


def ensure_default_model() -> None:
    args = sys.argv[1:]
    has_model_arg = any(arg == "--model-id" or arg.startswith("--model-id=") for arg in args)
    if not has_model_arg:
        sys.argv[1:1] = ["--model-id", settings.qwen_uncensored_model_id]


if __name__ == "__main__":
    ensure_default_model()
    raise SystemExit(chat.main())
