#!/usr/bin/env bash
# Pilot setup on alems-v100-explore (user cc): stock llama.cpp + official Qwen3-8B GGUF Q4_K_M / Q8_0.
set -euo pipefail
W=$HOME/claude-pilot
mkdir -p "$W"/{models,logs}
cd "$W"
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q cmake ninja huggingface_hub nvidia-ml-py requests
export PATH=$W/venv/bin:/usr/local/cuda/bin:$PATH

[ -d llama.cpp ] || git clone -q https://github.com/ggml-org/llama.cpp.git
git -C llama.cpp rev-parse HEAD > logs/llama_cpp_commit.txt
cmake -S llama.cpp -B llama.cpp/build -G Ninja -DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=70 \
  -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=OFF > logs/cmake.log 2>&1
cmake --build llama.cpp/build --target llama-server llama-bench -j 64 > logs/build.log 2>&1

venv/bin/python - <<'EOF'
from huggingface_hub import hf_hub_download
for f in ["Qwen3-8B-Q4_K_M.gguf", "Qwen3-8B-Q8_0.gguf"]:
    p = hf_hub_download("Qwen/Qwen3-8B-GGUF", f, local_dir="models")
    print(p)
EOF
sha256sum models/*.gguf > logs/models_sha256.txt
echo SETUP_DONE > logs/SETUP_DONE
