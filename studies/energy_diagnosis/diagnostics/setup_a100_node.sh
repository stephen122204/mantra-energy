#!/usr/bin/env bash
set -euo pipefail
# Opt-in bootstrap for a dedicated Ubuntu 24.04 CUDA 12.6 A100 node.
# Usage: bash setup_a100_node.sh REPOSITORY EXPECTED_COMMIT NEW_WORK_DIRECTORY
repo_dir=$(realpath "${1:?repository required}")
expected_commit=${2:?expected commit required}
work_dir=${3:?new absolute work directory required}
case "$work_dir" in /*) ;; *) echo 'work directory must be absolute' >&2; exit 2;; esac
test ! -e "$work_dir"
mkdir -p "$work_dir/logs"
cd "$repo_dir"
export PYTHONPATH="$repo_dir"
test "$(git rev-parse HEAD)" = "$expected_commit"
test -z "$(git status --porcelain)"
sudo -n apt-get update
sudo -n env DEBIAN_FRONTEND=noninteractive apt-get install -y python3-venv python3-dev libaio-dev libnuma-dev uuid-dev build-essential cmake ninja-build
python3 -m venv "${work_dir}/study-env"
"${work_dir}/study-env/bin/python" -m pip install -r requirements-study.txt huggingface_hub uv
"${work_dir}/study-env/bin/uv" python install 3.11
"${work_dir}/study-env/bin/uv" venv --seed --python 3.11 "${work_dir}/backend-env"
"${work_dir}/study-env/bin/python" -m studies.energy_diagnosis.moe.prepare download "${work_dir}/qwen3-30b-a3b-instruct-2507" > "${work_dir}/logs/model-download.log" 2>&1
"${work_dir}/study-env/bin/python" -m studies.energy_diagnosis.moe.prepare source "${work_dir}/moe-infinity"
"${work_dir}/backend-env/bin/python" -m pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cu126
"${work_dir}/backend-env/bin/python" -m pip install setuptools wheel ninja packaging setuptools-scm
git clone --depth 1 --branch v3.9.2 https://github.com/NVIDIA/cutlass.git "${work_dir}/cutlass"
test "$(git -C "${work_dir}/cutlass" rev-parse HEAD)" = ad7b2f5e84fcfa124cb02b91d5bd26d238c0459e
git clone --depth 1 --branch v3.4.0-c-cpp https://github.com/NVIDIA/NVTX.git "${work_dir}/nvtx"
test "$(git -C "${work_dir}/nvtx" rev-parse HEAD)" = f71a0342a464b8580ac8573e4349086a631c3992
export CUDA_HOME=/usr/local/cuda
export PATH="/usr/local/cuda/bin:$PATH"
export CUTLASS_DIR="${work_dir}/cutlass"
export CPATH="${work_dir}/nvtx/include"
export MAX_JOBS=8 MOE_ENABLE_SM90=0 TORCH_CUDA_ARCH_LIST=8.0
"${work_dir}/backend-env/bin/python" -m studies.energy_diagnosis.moe.prepare build "${work_dir}/moe-infinity"
"${work_dir}/study-env/bin/python" scripts/check_study_runtime.py
"${work_dir}/study-env/bin/python" scripts/check_moe_pipeline.py
date -u > "${work_dir}/logs/setup-completed.txt"
