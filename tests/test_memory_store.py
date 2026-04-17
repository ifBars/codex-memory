from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memory_store.py"


class MemoryStoreTests(unittest.TestCase):
    def run_cli(self, *args: str, root: Path) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env["CODEX_MEMORY_ROOT"] = str(root)
        return subprocess.run(
            [sys.executable, str(SCRIPT_PATH), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    def write_jsonl(self, path: Path, rows: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row))
                handle.write("\n")

    def test_migrates_legacy_files_into_semantic_tier(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.write_jsonl(
                root / "global.jsonl",
                [
                    {
                        "id": "legacy-global",
                        "scope": "global",
                        "kind": "preference",
                        "summary": "Prefer concise answers",
                        "details": "Keep explanations short.",
                        "confidence": "confirmed",
                        "created_at": "2026-04-08T00:00:00+00:00",
                    }
                ],
            )
            result = self.run_cli("list", root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            migrated = root / "semantic" / "global.jsonl"
            self.assertTrue(migrated.exists())
            payload = json.loads(migrated.read_text(encoding="utf-8").strip())
            self.assertEqual(payload["tier"], "semantic")
            self.assertEqual(payload["summary"], "Prefer concise answers")

    def test_recall_does_not_pull_unrelated_repo_memories(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo_a = str(root / "repo-a")
            repo_b = str(root / "repo-b")
            self.run_cli(
                "add",
                "--scope",
                "repo",
                "--tier",
                "semantic",
                "--repo",
                repo_a,
                "--kind",
                "workflow",
                "--summary",
                "Use bun for package management",
                "--details",
                "Do not use npm in repo A.",
                root=root,
            )
            self.run_cli(
                "add",
                "--scope",
                "repo",
                "--tier",
                "semantic",
                "--repo",
                repo_b,
                "--kind",
                "workflow",
                "--summary",
                "Run cargo test before push",
                "--details",
                "Repo B testing rule.",
                root=root,
            )
            result = self.run_cli(
                "recall",
                "--repo",
                repo_a,
                "--task",
                "fix package manager usage",
                root=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Use bun for package management", result.stdout)
            self.assertNotIn("Run cargo test before push", result.stdout)

    def test_episodic_memories_require_strong_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = str(root / "repo")
            self.run_cli(
                "add",
                "--scope",
                "repo",
                "--tier",
                "episodic",
                "--repo",
                repo,
                "--kind",
                "lesson",
                "--summary",
                "Null reference bug in memory migration",
                "--details",
                "Migration failed when repo metadata was missing.",
                root=root,
            )
            unrelated = self.run_cli(
                "recall",
                "--repo",
                repo,
                "--task",
                "write docs for package manager setup",
                root=root,
            )
            self.assertNotIn("Null reference bug in memory migration", unrelated.stdout)

            strong = self.run_cli(
                "recall",
                "--repo",
                repo,
                "--task",
                "debug null reference bug in migration",
                root=root,
            )
            self.assertIn("Null reference bug in memory migration", strong.stdout)

    def test_suggest_rejects_one_off_memory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.run_cli(
                "suggest",
                "--summary",
                "Fix PR #12 build failure today",
                "--details",
                "Temporary one-off task note.",
                root=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["accepted"])
            self.assertEqual(payload["reason"], "looks_one_off")

    def test_suggest_accepts_durable_repo_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.run_cli(
                "suggest",
                "--repo",
                str(root / "repo"),
                "--summary",
                "Use bun for package management",
                "--details",
                "Do not use npm or pnpm in this repo.",
                root=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["accepted"])
            self.assertEqual(payload["scope"], "repo")
            self.assertEqual(payload["tier"], "semantic")
            self.assertIn("Should I remember", payload["confirmation_question"])

    def test_suggest_rejects_narrow_incident_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.run_cli(
                "suggest",
                "--repo",
                str(root / "repo"),
                "--summary",
                "Dedicated police notice loops can come from invalid pursuit reactivation",
                "--details",
                "Dedicated police popup spam after arrest/release was traced to server authority patches restarting wanted/body-search responses for invalid targets and vehicle pursuit deactivation handing invalid targets back into foot pursuit.",
                root=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["accepted"])
            self.assertEqual(payload["reason"], "not_reusable_enough")
            self.assertIn("rewrite_candidate", payload)
            self.assertEqual(payload["rewrite_candidate"]["scope"], "repo")
            self.assertEqual(payload["rewrite_candidate"]["tier"], "semantic")
            self.assertEqual(payload["rewrite_candidate"]["kind"], "convention")
            self.assertNotEqual(
                payload["rewrite_candidate"]["summary"],
                payload["summary"],
            )
            self.assertTrue(payload["rewrite_candidate"]["details"])

    def test_suggest_rewrite_candidate_can_be_rechecked(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = str(root / "repo")
            initial = self.run_cli(
                "suggest",
                "--repo",
                repo,
                "--summary",
                "Dedicated police notice loops can come from invalid pursuit reactivation",
                "--details",
                (
                    "Dedicated police popup spam after arrest/release was traced to server authority "
                    "patches restarting wanted/body-search responses for invalid targets. Guard "
                    "dedicated police response patches against arrested, unconscious, or pursuit-none "
                    "players and suppress vehicle-to-foot fallback when the target is already invalid."
                ),
                root=root,
            )
            self.assertEqual(initial.returncode, 0, initial.stderr)
            initial_payload = json.loads(initial.stdout)
            rewrite = initial_payload["rewrite_candidate"]

            rewritten = self.run_cli(
                "suggest",
                "--repo",
                repo,
                "--summary",
                rewrite["summary"],
                "--details",
                rewrite["details"],
                "--kind",
                rewrite["kind"],
                "--scope",
                rewrite["scope"],
                root=root,
            )
            self.assertEqual(rewritten.returncode, 0, rewritten.stderr)
            rewritten_payload = json.loads(rewritten.stdout)
            self.assertTrue(rewritten_payload["accepted"])

    def test_sync_context_projects_repo_memories_into_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = str(root / "repo")
            self.run_cli(
                "add",
                "--scope",
                "repo",
                "--tier",
                "semantic",
                "--repo",
                repo,
                "--kind",
                "workflow",
                "--summary",
                "Use bun for package management",
                "--details",
                "Do not use npm or pnpm in this repo.",
                "--tags",
                "tooling",
                "package-manager",
                root=root,
            )

            result = self.run_cli("sync-context", "--repo", repo, root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["scope"], "repo")
            self.assertEqual(len(payload["documents"]), 1)

            repo_key = payload["repo_key"]
            context_root = root / "context-repositories" / "repos" / repo_key
            manifest = json.loads((context_root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["counts"]["sections"]["system"], 1)

            document_path = context_root / "system" / "workflow" / "use-bun-for-package-management.md"
            text = document_path.read_text(encoding="utf-8")
            self.assertIn('summary: "Use bun for package management"', text)
            self.assertIn("Do not use npm or pnpm in this repo.", text)

    def test_doctor_reports_missing_context_manifest_before_sync(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = str(root / "repo")
            self.run_cli(
                "add",
                "--scope",
                "repo",
                "--tier",
                "semantic",
                "--repo",
                repo,
                "--kind",
                "workflow",
                "--summary",
                "Use bun for package management",
                "--details",
                "Do not use npm or pnpm in this repo.",
                root=root,
            )

            result = self.run_cli("doctor", "--repo", repo, root=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            issue_codes = {issue["code"] for issue in payload["issues"]}
            self.assertIn("missing_manifest", issue_codes)
            self.assertIn("missing_documents", issue_codes)

    def test_suggest_accepts_incident_when_it_encodes_reusable_rule(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result = self.run_cli(
                "suggest",
                "--repo",
                str(root / "repo"),
                "--summary",
                "Guard dedicated police response patches against invalid targets",
                "--details",
                "Guard dedicated police response patches against arrested, unconscious, or pursuit-none players and suppress vehicle-to-foot fallback when the target is already invalid.",
                root=root,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["accepted"])
            self.assertEqual(payload["scope"], "repo")

    def test_promote_core_and_export_agents(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = str(root / "repo")
            add_result = self.run_cli(
                "add",
                "--scope",
                "repo",
                "--tier",
                "semantic",
                "--repo",
                repo,
                "--kind",
                "convention",
                "--summary",
                "Use bun for package management",
                "--details",
                "Do not use npm or pnpm in this repo.",
                root=root,
            )
            self.assertEqual(add_result.returncode, 0, add_result.stderr)
            semantic_path = next((root / "semantic" / "repos").glob("*.jsonl"))
            memory_id = json.loads(semantic_path.read_text(encoding="utf-8").strip())["id"]

            promote = self.run_cli("promote-core", "--id", memory_id, root=root)
            self.assertEqual(promote.returncode, 0, promote.stderr)

            export = self.run_cli("export-agents", "--repo", repo, root=root)
            self.assertEqual(export.returncode, 0, export.stderr)
            self.assertIn("Use bun for package management", export.stdout)


if __name__ == "__main__":
    unittest.main()
