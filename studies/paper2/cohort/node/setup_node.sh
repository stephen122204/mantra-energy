#!/usr/bin/env bash
# Node setup for the shared-server cohort runner (run as cc on the GPU node, BEFORE any measurement).
# Usage: bash setup_node.sh <repo-commit> <bundle>   (W=$HOME/paper2 by default)
#   <bundle> is a git bundle of the tested commit copied from the controller (the team repo is private).
# Installs: Python 3.11 venv (uv), vllm==0.10.2, mistral_common==1.8.5, ALEMS study requirements;
# downloads the pinned Devstral-Small-2507 checkpoints and NetworkX 3.4.2 source; writes manifests.
# Nothing here runs a model. Re-running is idempotent; pinned revisions are verified.
set -euo pipefail
COMMIT="${1:?usage: setup_node.sh <repo-commit> <bundle>}"
BUNDLE="${2:?usage: setup_node.sh <repo-commit> <bundle>}"
export W="${W:-$HOME/paper2}"
mkdir -p "$W"/{models,logs,manifests}
cd "$W"
export PATH="$HOME/.local/bin:$PATH"

# 1. repository at the exact tested commit
git bundle verify -q "$BUNDLE"
if [ ! -d repo/.git ]; then git clone -q "$BUNDLE" repo; fi
git -C repo fetch -q "$BUNDLE" "+refs/heads/*:refs/remotes/bundle/*"
git -C repo checkout -q --detach "$COMMIT"
test -z "$(git -C repo status --porcelain)"
git -C repo rev-parse HEAD > manifests/repo-commit.txt

# 2. Python 3.11 environment
command -v uv >/dev/null || python3 -m pip install -q --user uv
[ -x venv/bin/python ] || uv venv -q --python 3.11 venv
VP="$W/venv/bin/python"
uv pip install -q --python "$VP" "vllm==0.10.2" "mistral_common==1.8.5" "huggingface_hub>=0.34" \
  -r repo/requirements-study.txt -r repo/requirements-task-screen.txt
uv pip freeze --python "$VP" > manifests/pip-freeze.txt
"$VP" -c "import vllm, torch, mistral_common; print('vllm', vllm.__version__, 'torch', torch.__version__, 'cuda', torch.version.cuda, 'mistral_common', mistral_common.__version__)" \
  | tee manifests/engine-versions.txt

# 3. pinned checkpoints (HF-format shards only; the BF16 repo also ships a duplicate consolidated file)
"$VP" - <<'EOF'
import json, os
from huggingface_hub import snapshot_download
W = os.environ.get("W", os.path.expanduser("~/paper2"))
pins = {
  "devstral-bf16":  ("mistralai/Devstral-Small-2507", "bd165ab26cebbcc2eea2c4ecbfc07f3ac42b3c39"),
  "devstral-w8a8":  ("RedHatAI/Devstral-Small-2507-quantized.w8a8", "b152b0574658cdd159721472ebf5353d8d199451"),
  "devstral-w4a16": ("RedHatAI/Devstral-Small-2507-quantized.w4a16", "bb96f0d1a876d6f6f3ed657b6a965328697ba2f9"),
}
for name, (repo, rev) in pins.items():
    path = snapshot_download(repo, revision=rev, local_dir=f"{W}/models/{name}",
                             allow_patterns=["*.json", "model*.safetensors", "tekken.json", "*.txt", "recipe.yaml"],
                             ignore_patterns=["consolidated*"])
    print(name, path)
json.dump({k: {"repo": r, "revision": v} for k, (r, v) in pins.items()}, open(f"{W}/manifests/model-pins.json", "w"), indent=1)
EOF
for d in models/*/; do (cd "$d" && find . -type f ! -name '*.lock' -print0 | sort -z | xargs -0 sha256sum) > "manifests/$(basename "$d")-sha256.txt"; done

# 4. NetworkX 3.4.2 source for the repository-repair tasks
if [ ! -d networkx-src/.git ]; then git clone -q https://github.com/networkx/networkx.git networkx-src; fi
git -C networkx-src checkout -q --detach 2acf1590f82757c01a57b81b8c5dfb79e60aa416
git -C networkx-src rev-parse HEAD > manifests/networkx-commit.txt

# 5. SWE-bench harness in its own environment (grading only; never imported by the runner)
[ -x venv-swebench/bin/python ] || uv venv -q --python 3.11 venv-swebench
uv pip install -q --python venv-swebench/bin/python "swebench==4.1.0"
uv pip freeze --python venv-swebench/bin/python > manifests/swebench-freeze.txt
command -v docker >/dev/null && docker version --format '{{.Server.Version}}' > manifests/docker-version.txt || echo "docker unavailable" > manifests/docker-version.txt

(cd manifests && sha256sum ./*.txt ./*.json > ../manifests.SHA256SUMS)
echo SETUP_DONE | tee logs/SETUP_DONE
