"""Publish one immutable context note without staging the caller's working tree."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

AUTHORS = {"stephen", "alex", "aldric", "nitheesh"}
BRANCH = "main"
EXPECTED_REMOTE = "https://github.com/stephen122204/mantra-energy.git"
HEADINGS = (
    "Task and current understanding", "Ideas and hypotheses", "Decisions and rationale",
    "Changes and artifacts", "Tests and evidence", "Open questions and disagreements",
    "Next actions and handoff",
)


def git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and result.returncode:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "Git command failed")
    return result


def normalize_remote(value):
    value = value.strip().rstrip("/")
    if value.startswith("git@github.com:"):
        value = "https://github.com/" + value[len("git@github.com:"):]
    return value.removesuffix(".git")


def publish(repo, author, turn_id, note, expected_remote=EXPECTED_REMOTE, retries=3):
    repo = Path(repo).resolve()
    if author not in AUTHORS:
        raise ValueError("Author must be stephen, alex, aldric or nitheesh")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,119}", turn_id):
        raise ValueError("Use a unique alphanumeric/dash/underscore turn ID, max 120 characters")
    note = note.strip() + "\n"
    if len(note.encode()) > 256_000:
        raise ValueError("Link large artifacts; keep the reviewable turn note below 256 KB")
    missing = [h for h in HEADINGS if f"## {h}\n" not in note]
    if missing:
        raise ValueError("Missing summary sections: " + ", ".join(missing))
    # Check both fetch and push destinations: origin can have a separate pushurl.
    for args in (("remote", "get-url", "origin"), ("remote", "get-url", "--push", "origin")):
        remote = git(repo, *args).stdout.strip()
        if normalize_remote(remote) != normalize_remote(expected_remote):
            raise ValueError("Origin must fetch and push to the intended private team repository")
    relative = Path("docs/team") / author / "turns" / f"{turn_id}.md"
    latest = Path("docs/team") / author / "LATEST.md"
    last_error = ""
    for attempt in range(retries):
        git(repo, "fetch", "origin", f"refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}")
        base = git(repo, "rev-parse", f"refs/remotes/origin/{BRANCH}").stdout.strip()
        with tempfile.TemporaryDirectory(prefix="alems-context-") as temp:
            worktree = Path(temp) / "worktree"
            git(repo, "worktree", "add", "--detach", str(worktree), base)
            try:
                target = worktree / relative
                if target.exists():
                    if target.read_text(encoding="utf-8") != note:
                        raise ValueError("Turn ID already exists with different content; use a new turn ID")
                    return {"status": "already_published", "branch": BRANCH, "path": str(relative), "verified_remote_commit": base}
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(note, encoding="utf-8")
                (worktree / latest).write_text(
                    f"# Latest published context: {author}\n\n"
                    f"[Immutable turn record](turns/{turn_id}.md)\n\n" + note,
                    encoding="utf-8",
                )
                git(worktree, "add", "--", relative.as_posix(), latest.as_posix())
                staged = set(git(worktree, "diff", "--cached", "--name-only", "-z").stdout.rstrip("\0").split("\0"))
                if staged != {relative.as_posix(), latest.as_posix()}:
                    raise RuntimeError("Unexpected staged paths; refusing a broad context push")
                git(worktree, "diff", "--cached", "--check")
                git(worktree, "commit", "-m", f"context({author}): {turn_id}")
                commit = git(worktree, "rev-parse", "HEAD").stdout.strip()
                pushed = git(worktree, "push", "origin", f"HEAD:refs/heads/{BRANCH}", check=False)
                if pushed.returncode == 0:
                    return {"status": "published", "branch": BRANCH, "path": str(relative), "commit": commit}
                # Re-fetch and reapply only this note; never force-push or merge code.
                last_error = pushed.stderr.strip()
            finally:
                git(repo, "worktree", "remove", "--force", str(worktree))
    raise RuntimeError(f"Context push failed after {retries} attempts; retain your local note. {last_error}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--author", choices=sorted(AUTHORS), required=True)
    parser.add_argument("--turn-id", required=True)
    parser.add_argument("--note", type=Path, required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    try:
        receipt = publish(repo, args.author, args.turn_id, args.note.read_text(encoding="utf-8"))
    except (ValueError, RuntimeError, OSError) as error:
        parser.exit(1, f"Publication failed: {error}\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
