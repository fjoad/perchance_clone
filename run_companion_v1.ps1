$env:HF_HOME = "F:\huggingface\models"
$env:HF_HUB_CACHE = "F:\huggingface\models\hub"
$env:HUGGINGFACE_HUB_CACHE = "F:\huggingface\models\hub"
$env:TRANSFORMERS_CACHE = ""
$env:PYTHONDONTWRITEBYTECODE = "1"
$env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True"

& "F:\anaconda3\envs\companion_v1\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
