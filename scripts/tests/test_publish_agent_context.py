"""Exercise publishing against disposable local Git repos; no GitHub writes."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("publisher", Path(__file__).parents[1] / "publish_agent_context.py")
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)


class PublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.remote = self.base / "remote.git"
        self.repo = self.base / "repo"
        subprocess.run(["git", "init", "--bare", str(self.remote)], check=True, capture_output=True)
        subprocess.run(["git", "init", str(self.repo)], check=True, capture_output=True)
        publisher.git(self.repo, "config", "user.name", "Fixture Author")
        publisher.git(self.repo, "config", "user.email", "fixture@example.invalid")
        publisher.git(self.repo, "switch", "-c", publisher.BRANCH)
        (self.repo / "code.py").write_text("original\n")
        publisher.git(self.repo, "add", "code.py")
        publisher.git(self.repo, "commit", "-m", "fixture baseline")
        publisher.git(self.repo, "remote", "add", "origin", str(self.remote))
        publisher.git(self.repo, "push", "origin", publisher.BRANCH)
        self.note = "# Fixture summary\n\n" + "\n\n".join(f"## {h}\n\nFixture evidence." for h in publisher.HEADINGS) + "\n"

    def publish(self, author="alex", turn="fixture-1", note=None):
        return publisher.publish(self.repo, author, turn, note or self.note, expected_remote=str(self.remote))

    def remote_text(self, path):
        return publisher.git(self.remote, "show", f"refs/heads/{publisher.BRANCH}:{path}").stdout

    def test_dirty_code_is_not_pushed_and_repeat_is_idempotent(self):
        (self.repo / "code.py").write_text("unrelated staged edit\n")
        publisher.git(self.repo, "add", "code.py")
        before = publisher.git(self.repo, "status", "--porcelain").stdout
        first = self.publish()
        self.assertEqual(first["status"], "published")
        self.assertEqual(self.remote_text("code.py"), "original\n")
        self.assertEqual(publisher.git(self.repo, "status", "--porcelain").stdout, before)
        self.assertEqual(self.publish()["status"], "already_published")
        with self.assertRaisesRegex(ValueError, "different content"):
            self.publish(note=self.note + "Correction\n")

    def test_validation_and_wrong_destination(self):
        with self.assertRaises(ValueError):
            self.publish(author="unknown")
        with self.assertRaises(ValueError):
            self.publish(turn="../escape")
        with self.assertRaisesRegex(ValueError, "Missing summary"):
            self.publish(note="Incomplete note")
        publisher.git(self.repo, "remote", "set-url", "--push", "origin", str(self.base / "wrong.git"))
        with self.assertRaisesRegex(ValueError, "Origin must"):
            self.publish()

    def test_concurrent_remote_advance_preserves_both_notes(self):
        real_git = publisher.git
        advanced = False

        def intercept(repo, *args, **kwargs):
            nonlocal advanced
            if args and args[0] == "push" and not advanced:
                advanced = True
                # Another author's genuine commit reaches the remote before this push.
                publisher.publish(self.repo, "aldric", "concurrent-1", self.note, expected_remote=str(self.remote))
            return real_git(repo, *args, **kwargs)

        with patch.object(publisher, "git", side_effect=intercept):
            result = self.publish()
        self.assertEqual(result["status"], "published")
        self.assertEqual(self.remote_text("agent context md/alex/turns/fixture-1.md"), self.note)
        self.assertEqual(self.remote_text("agent context md/aldric/turns/concurrent-1.md"), self.note)

    def test_rejected_push_keeps_source_note_and_cleans_worktrees(self):
        source = self.base / "pending-note.md"
        source.write_text(self.note)
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        before = publisher.git(self.remote, "rev-parse", f"refs/heads/{publisher.BRANCH}").stdout
        with self.assertRaisesRegex(RuntimeError, "retain your local note"):
            self.publish(note=source.read_text())
        self.assertEqual(source.read_text(), self.note)
        self.assertEqual(publisher.git(self.remote, "rev-parse", f"refs/heads/{publisher.BRANCH}").stdout, before)
        self.assertEqual(publisher.git(self.repo, "worktree", "list", "--porcelain").stdout.count("worktree "), 1)


if __name__ == "__main__":
    unittest.main()
