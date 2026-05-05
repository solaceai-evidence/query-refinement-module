#!/bin/bash

set -euo pipefail

MODEL="meta-llama/Llama-3.1-8B-Instruct"
if [ "$#" -gt 0 ]; then
    MODEL="$1"
    shift
fi

PORT="${PORT:-8000}"
DTYPE="${VLLM_DTYPE:-bfloat16}"
MAX_MODEL_LEN="${VLLM_MAX_MODEL_LEN:-16384}"
HOST_OS="$(uname -s)"

if ! command -v vllm >/dev/null 2>&1; then
    echo "vllm is not installed in the current environment."
    echo "Install it first, for example: pip install vllm"
    exit 1
fi

CUDA_AVAILABLE="$({ python - <<'PY'
try:
    import torch
    print("1" if torch.cuda.is_available() else "0")
except Exception:
    print("0")
PY
} | tr -d '[:space:]')"

if [[ "$MODEL" == *"70B"* ]] && { [ "$HOST_OS" = "Darwin" ] || [ "$CUDA_AVAILABLE" != "1" ]; }; then
    echo "Refusing to start $MODEL on this host."
    if [ "$HOST_OS" = "Darwin" ]; then
        echo "vLLM runs CPU-only on macOS, so the 70B model will be killed during load or thrash memory."
    else
        echo "No NVIDIA CUDA device was detected, so the 70B model cannot be served safely."
    fi
    echo "Use the default Llama 3.1 8B model for local testing: ./start_vllm.sh"
    echo "Or run the 70B model on a Linux multi-GPU machine and point QUERY_REFINEMENT_LLM_API_BASE there."
    exit 1
fi

echo "Starting vLLM server"
echo "  model: $MODEL"
echo "  port: $PORT"
echo "  dtype: $DTYPE"
echo "  max-model-len: $MAX_MODEL_LEN"

exec vllm serve "$MODEL" --port "$PORT" --dtype "$DTYPE" --max-model-len "$MAX_MODEL_LEN" "$@"