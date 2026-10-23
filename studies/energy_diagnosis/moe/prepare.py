"""Explicit source/download/build stages; importing this module does no installation."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
COMMIT = "6da092fc98e7246bfa1b2f9b2a480524b8697a7e"
REVISION = "0d7cf23991f47feeb3a57ecb4c9cee8ea4a17bfe"
MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
PATTERNS = ("*.json", "*.safetensors", "*.jinja", "*.txt")


def file_sha(path):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def source(path):
    path = Path(path).resolve()
    if path.exists():
        raise ValueError("source destination must not exist; preserve existing builds")
    subprocess.run(
        [
            "git",
            "clone",
            "--no-checkout",
            "https://github.com/EfficientMoE/MoE-Infinity.git",
            str(path),
        ],
        check=True,
    )
    subprocess.run(["git", "checkout", "--detach", COMMIT], cwd=path, check=True)
    subprocess.run(
        ["git", "submodule", "update", "--init", "--recursive"], cwd=path, check=True
    )
    patch = HERE / "patches/moe-infinity-transfer-lifecycle.patch"
    subprocess.run(["git", "apply", "--check", str(patch)], cwd=path, check=True)
    subprocess.run(["git", "apply", str(patch)], cwd=path, check=True)
    shutil.copyfile(
        HERE / "native/transfer_lifecycle.h",
        path / "core/prefetch/alems_transfer_lifecycle.h",
    )
    (path / "alems-source.json").write_text(
        json.dumps(
            dict(
                commit=COMMIT,
                patch_sha256=file_sha(patch),
                header_sha256=file_sha(HERE / "native/transfer_lifecycle.h"),
            ),
            indent=2,
        )
        + "\n"
    )


def download(path, model=MODEL, revision=REVISION, allow_patterns=PATTERNS):
    """Pinned snapshot plus alems-weights.json (sha256 of every file). Defaults are the Qwen
    checkpoint; a llama.cpp model directory needs only tokenizer/template/config files, e.g.
    --model mistralai/Devstral-Small-2-24B-Instruct-2512 --revision <sha> --pattern tokenizer.json ..."""
    from huggingface_hub import snapshot_download

    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        model,
        revision=revision,
        local_dir=str(path),
        allow_patterns=list(allow_patterns),
    )
    manifest = dict(
        model=model,
        revision=revision,
        files={
            p.name: file_sha(p)
            for p in path.iterdir()
            if p.is_file() and p.name != "alems-weights.json"
        },
    )
    (path / "alems-weights.json").write_text(json.dumps(manifest, indent=2) + "\n")


def build(path):
    path = Path(path).resolve()
    expected = json.loads((path / "alems-source.json").read_text())
    if expected != dict(
        commit=COMMIT,
        patch_sha256=file_sha(HERE / "patches/moe-infinity-transfer-lifecycle.patch"),
        header_sha256=file_sha(HERE / "native/transfer_lifecycle.h"),
    ):
        raise RuntimeError("prepared source does not match this control package")
    if (
        subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=path, text=True
        ).strip()
        != COMMIT
    ):
        raise RuntimeError("wrong backend source commit")
    actual_diff = subprocess.check_output(["git", "diff", "--binary"], cwd=path)
    if (
        hashlib.sha256(actual_diff).hexdigest() != expected["patch_sha256"]
        or file_sha(path / "core/prefetch/alems_transfer_lifecycle.h")
        != expected["header_sha256"]
    ):
        raise RuntimeError("backend source was modified after patch preparation")
    import torch

    if torch.__version__.split("+")[0] != "2.10.0":
        raise RuntimeError(
            "install torch==2.10.0 CUDA build in the isolated backend environment first"
        )
    if not torch.version.cuda or not shutil.which("nvcc"):
        raise RuntimeError(
            "GPU PyTorch and a matching CUDA toolkit are required; CPU-only build is not accepted"
        )
    # Keep the study's lightweight environment separate. User invokes this in backend venv.
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "-c",
            str(HERE / "backend-constraints.txt"),
            "-r",
            str(path / "requirements.txt"),
        ],
        check=True,
    )
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-build-isolation",
            "--no-deps",
            str(path),
        ],
        check=True,
    )
    spec = importlib.util.find_spec("moe_infinity")
    package = Path(spec.origin).parent
    files = {
        str(p): file_sha(p)
        for p in package.rglob("*")
        if p.suffix in {".py", ".so", ".pyd"}
    }
    if not any(
        Path(p).name.startswith("_store.") and Path(p).suffix == ".so" for p in files
    ):
        raise RuntimeError("native store extension missing; build is not accepted")
    freeze = subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True)
    manifest = dict(
        source=expected,
        python=sys.version,
        executable=sys.executable,
        cuda=torch.version.cuda,
        files=files,
        pip_freeze=freeze,
    )
    (path / "alems-build.json").write_text(json.dumps(manifest, indent=2) + "\n")


def verify_build(path):
    manifest = json.loads(path.read_text())
    if (
        manifest["source"]["commit"] != COMMIT
        or manifest["source"]["patch_sha256"]
        != file_sha(HERE / "patches/moe-infinity-transfer-lifecycle.patch")
        or manifest["source"]["header_sha256"]
        != file_sha(HERE / "native/transfer_lifecycle.h")
    ):
        raise RuntimeError("backend build fingerprint differs from control package")
    package = Path(importlib.util.find_spec("moe_infinity").origin).parent.resolve()
    if str(package / "__init__.py") not in manifest["files"]:
        raise RuntimeError("loaded backend is not the manifested installation")
    for name, digest in manifest["files"].items():
        if file_sha(name) != digest:
            raise RuntimeError(f"backend file changed: {name}")
    actual_freeze = subprocess.check_output(
        [sys.executable, "-m", "pip", "freeze"], text=True
    )
    if actual_freeze != manifest["pip_freeze"]:
        raise RuntimeError("backend dependencies changed after native build")
    return dict(
        manifest_sha256=file_sha(path),
        source=manifest["source"],
        cuda=manifest["cuda"],
        pip_freeze=manifest["pip_freeze"],
    )


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("stage", choices=["source", "download", "build"])
    p.add_argument("path")
    p.add_argument("--model", help="download only: Hugging Face repository (default: the Qwen checkpoint)")
    p.add_argument("--revision", help="download only: pinned commit; required with --model")
    p.add_argument("--pattern", action="append", help="download only: allow pattern, repeatable")
    args = p.parse_args()
    if args.stage != "download" and (args.model or args.revision or args.pattern):
        p.error("--model, --revision and --pattern apply to download only")
    if args.stage == "download":
        if args.model and (not args.revision or len(args.revision) != 40):
            p.error("--model requires a pinned 40-character --revision")
        download(args.path, args.model or MODEL, args.revision or REVISION, args.pattern or PATTERNS)
        return
    globals()[args.stage](args.path)


if __name__ == "__main__":
    main()
