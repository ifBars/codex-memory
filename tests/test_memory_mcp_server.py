from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import anyio


SERVER_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memory_mcp_server.py"
STORE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "memory_store.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class MemoryMcpServerTests(unittest.TestCase):
    def test_lists_expected_resources_and_reads_repo_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            os.environ["CODEX_MEMORY_ROOT"] = str(root)
            memory_store = load_module("memory_store_test", STORE_PATH)
            server_module = load_module("memory_mcp_server_test", SERVER_PATH)

            repo_path = str(root / "repo")
            args = type(
                "Args",
                (),
                {
                    "scope": "repo",
                    "tier": "semantic",
                    "repo": repo_path,
                    "kind": "convention",
                    "summary": "Use bun for package management",
                    "details": "Do not use npm or pnpm in this repo.",
                    "tags": ["tooling"],
                    "source": "user-confirmed",
                    "confidence": "confirmed",
                    "status": "active",
                },
            )()
            memory_store.ensure_layout()
            entry = memory_store.build_entry(args)
            path = memory_store.tier_path(entry.tier, entry.scope, repo=entry.repo_path, repo_key=entry.repo_key)
            memory_store.upsert_entry(path, entry)
            memory_store.sync_context_repository("repo", repo_path)

            server = server_module.create_server()
            resources = anyio.run(server.list_resources)
            uris = {str(resource.uri) for resource in resources}
            self.assertIn("memory://overview", uris)
            self.assertIn("memory://repositories", uris)
            self.assertIn("memory://context-repositories", uris)
            self.assertIn("memory://global/core", uris)
            self.assertIn("memory://global/semantic", uris)
            self.assertIn("memory://global/context-repo", uris)

            templates = anyio.run(server.list_resource_templates)
            template_uris = {template.uriTemplate for template in templates}
            self.assertIn("memory://repo/{repo_key}/semantic", template_uris)
            self.assertIn("memory://repo/{repo_key}/context-repo", template_uris)

            repo_key = memory_store.repo_key_for(repo_path)
            contents = anyio.run(server.read_resource, f"memory://repo/{repo_key}/semantic")
            payload = json.loads(contents[0].content)
            self.assertEqual(payload["repo_key"], repo_key)
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["entries"][0]["summary"], "Use bun for package management")

            context_contents = anyio.run(server.read_resource, f"memory://repo/{repo_key}/context-repo")
            context_payload = json.loads(context_contents[0].content)
            self.assertEqual(context_payload["repo_key"], repo_key)
            self.assertEqual(context_payload["counts"]["sections"]["system"], 1)
            self.assertIn("manifest.json", context_payload["tree"])

    def tearDown(self) -> None:
        os.environ.pop("CODEX_MEMORY_ROOT", None)


if __name__ == "__main__":
    unittest.main()
