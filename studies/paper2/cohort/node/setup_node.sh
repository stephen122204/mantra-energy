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
if [ ! -d repo/.git ]; then git clone -q "$BUNDLE" repo; fi
git -C repo bundle verify -q "$BUNDLE"   # older git needs a repository to verify a bundle
git -C repo fetch -q "$BUNDLE" "+refs/heads/*:refs/remotes/bundle/*"
git -C repo checkout -q --detach "$COMMIT"
test -z "$(git -C repo status --porcelain)"
git -C repo rev-parse HEAD > manifests/repo-commit.txt

# 1b. CPU-package energy counters: root-only by default on CC images; make them readable (lost on reboot)
if ls /sys/class/powercap/intel-rapl:*/energy_uj >/dev/null 2>&1; then
  sudo -n chmod a+r /sys/class/powercap/intel-rapl:*/energy_uj /sys/class/powercap/intel-rapl:*:*/energy_uj 2>/dev/null || true
  for f in /sys/class/powercap/intel-rapl:*/energy_uj; do printf '%s %s\n' "$f" "$(cat "$f" 2>&1)"; done > manifests/rapl-readable.txt
fi

# 2. Python 3.11 environment
if ! command -v uv >/dev/null; then
  python3 -m pip --version >/dev/null 2>&1 || { sudo -n apt-get update -qq && sudo -n apt-get install -y -qq python3-pip; }
  python3 -m pip install -q --user uv
fi
[ -x venv/bin/python ] || uv venv -q --python 3.11 venv
VP="$W/venv/bin/python"
uv pip install -q --python "$VP" pip  # repo tasks record `python -m pip freeze` as tool identity; uv venvs omit pip
# transformers pinned below 5: vLLM 0.10.2 only requires >=4.55.2, and under transformers 5 the config
# no longer exposes rope_theta (moved to rope_parameters), so vLLM silently uses base 10000 instead of
# Devstral's 1e9 and generation degrades past a few hundred tokens (found on gigaio-compute-08).
uv pip install -q --python "$VP" "vllm==0.10.2" "transformers==4.56.2" "mistral_common==1.8.5" "huggingface_hub>=0.34" \
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
# 6. Docker for the SWE-bench containers (CC images ship without it); cc joins the docker group,
#    which takes effect in new ssh sessions (later steps run in their own sessions)
if ! command -v docker >/dev/null; then
  sudo -n apt-get update -qq && sudo -n apt-get install -y -qq docker.io
  sudo -n systemctl enable --now docker
fi
id -nG "$USER" | grep -qw docker || sudo -n usermod -aG docker "$USER"
sudo -n docker version --format '{{.Server.Version}}' > manifests/docker-version.txt || echo "docker unavailable" > manifests/docker-version.txt

(cd manifests && sha256sum ./*.txt ./*.json > ../manifests.SHA256SUMS)
echo SETUP_DONE | tee logs/SETUP_DONE
