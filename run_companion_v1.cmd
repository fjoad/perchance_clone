@echo off
set HF_HOME=F:\huggingface\models
set HF_HUB_CACHE=F:\huggingface\models\hub
set HUGGINGFACE_HUB_CACHE=F:\huggingface\models\hub
set TRANSFORMERS_CACHE=
set PYTHONDONTWRITEBYTECODE=1
set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

"F:\anaconda3\envs\companion_v1\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
