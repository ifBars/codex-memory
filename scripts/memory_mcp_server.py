#!/usr/bin/env python
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import memory_store


SERVER_NAME = "memory"
PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def _ensure_layout() -> None:
    memory_store.ensure_layout()


def _normalize_repo_path(repo_path: str | None) -> str | None:
    if not repo_path:
        return None
    return str(Path(repo_path).resolve())


def _entry_payload(entry: memory_store.MemoryEntry) -> dict[str, Any]:
    return entry.to_dict()


def _bucket_payload(scope: str, tier: str, *, repo_path: str | None = None, repo_key: str | None = None) -> dict[str, Any]:
    _ensure_layout()
    path = memory_store.tier_path(tier, scope, repo=repo_path, repo_key=repo_key)
    entries = memory_store.active_entries(memory_store.load_entries(path)) if path.exists() else []
    resolved_repo_path = repo_path
    if not resolved_repo_path and entries:
        resolved_repo_path = entries[0].repo_path
    payload: dict[str, Any] = {
        "scope": scope,
        "tier": tier,
        "path": str(path),
        "count": len(entries),
        "entries": [_entry_payload(entry) for entry in memory_store.sort_entries(entries)],
    }
    if repo_key:
        payload["repo_key"] = repo_key
    if resolved_repo_path:
        payload["repo_path"] = resolved_repo_path
    return payload


def _known_repositories() -> list[dict[str, Any]]:
    _ensure_layout()
    repositories: dict[str, dict[str, Any]] = {}
    for entry in memory_store.load_scope_entries(include_all_repos=True):
        if entry.scope != "repo" or not entry.repo_key:
            continue
        current = repositories.setdefault(
            entry.repo_key,
            {
                "repo_key": entry.repo_key,
                "repo_path": entry.repo_path,
                "tiers": set(),
                "count": 0,
            },
        )
        if not current["repo_path"] and entry.repo_path:
            current["repo_path"] = entry.repo_path
        current["tiers"].add(entry.tier)
        current["count"] += 1
    result: list[dict[str, Any]] = []
    for repo_key in sorted(repositories):
        item = repositories[repo_key]
        result.append(
            {
                "repo_key": item["repo_key"],
                "repo_path": item["repo_path"],
                "tiers": sorted(item["tiers"]),
                "count": item["count"],
            }
        )
    return result


def _known_context_repositories() -> list[dict[str, Any]]:
    _ensure_layout()
    repositories: list[dict[str, Any]] = []
    global_manifest = memory_store.load_context_manifest("global")
    repositories.append(
        {
            "scope": "global",
            "repo_key": None,
            "repo_path": None,
            "root": str(memory_store.context_repo_path("global")),
            "manifest_path": str(memory_store.context_manifest_path("global")),
            "exists": global_manifest is not None,
            "document_count": len(global_manifest.get("documents", [])) if global_manifest else 0,
        }
    )
    for repo in _known_repositories():
        manifest = memory_store.load_context_manifest("repo", repo_key=repo["repo_key"])
        repositories.append(
            {
                "scope": "repo",
                "repo_key": repo["repo_key"],
                "repo_path": repo["repo_path"],
                "root": str(memory_store.context_repo_path("repo", repo_key=repo["repo_key"])),
                "manifest_path": str(memory_store.context_manifest_path("repo", repo_key=repo["repo_key"])),
                "exists": manifest is not None,
                "document_count": len(manifest.get("documents", [])) if manifest else 0,
            }
        )
    return repositories


def _repo_path_for_key(repo_key: str) -> str | None:
    for repo in _known_repositories():
        if repo["repo_key"] == repo_key:
            return repo["repo_path"]
    return None


def _format_json(payload: dict[str, Any] | list[dict[str, Any]]) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True)


def _recall_payload(task: str, repo_path: str | None = None, limit: int = 5) -> dict[str, Any]:
    _ensure_layout()
    repo = _normalize_repo_path(repo_path)
    terms = memory_store.tokenize_query(task)
    repo_key = memory_store.repo_key_for(repo)

    core_entries = memory_store.load_tier_entries("core", "global")
    semantic_entries = memory_store.load_tier_entries("semantic", "global")
    episodic_entries: list[memory_store.MemoryEntry] = []

    if repo:
        core_entries.extend(memory_store.load_tier_entries("core", "repo", repo))
        semantic_entries.extend(memory_store.load_tier_entries("semantic", "repo", repo))
        episodic_entries.extend(memory_store.load_tier_entries("episodic", "repo", repo))

    semantic_hits = memory_store.select_semantic(
        semantic_entries,
        terms,
        repo_key,
        limit=max(limit - len(core_entries), 0),
    )
    episodic_hits = memory_store.select_episodic(
        episodic_entries,
        terms,
        repo_key,
        limit=min(2, limit),
    )
    surfaced = memory_store.sort_entries(core_entries) + semantic_hits + episodic_hits
    memory_store.touch_entries(surfaced)

    return {
        "task": task,
        "repo_path": repo,
        "core": [_entry_payload(entry) for entry in memory_store.sort_entries(core_entries)],
        "semantic": [_entry_payload(entry) for entry in semantic_hits],
        "episodic": [_entry_payload(entry) for entry in episodic_hits],
    }


def _suggest_payload(
    summary: str,
    details: str = "",
    *,
    repo_path: str | None = None,
    kind: str | None = None,
    scope: str = "auto",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    _ensure_layout()
    repo = _normalize_repo_path(repo_path)
    summary = summary.strip()
    details = details.strip()
    summary_text = summary.lower()
    text = f"{summary} {details}".lower()

    reason = None
    if not summary or len(summary) < 8:
        reason = "summary_too_short"
    elif any(pattern in text for pattern in memory_store.SECRET_PATTERNS):
        reason = "contains_secret_like_content"
    elif any(pattern in text for pattern in memory_store.ONE_OFF_PATTERNS):
        reason = "looks_one_off"

    inferred_kind = kind or memory_store.infer_kind(summary, details)
    inferred_scope = scope if scope != "auto" else memory_store.infer_scope(inferred_kind, repo, summary, details)
    tier = memory_store.infer_tier(inferred_kind, summary, details, inferred_scope)
    normalized_tags = memory_store.normalize_tags(tags or [])
    incident_like = (
        any(pattern in text for pattern in memory_store.INCIDENT_PATTERNS)
        or inferred_kind == "lesson"
        or tier == "episodic"
    )
    summary_reusable_rule = any(pattern in summary_text for pattern in memory_store.REUSABLE_RULE_PATTERNS)
    rewrite_candidate = None
    if reason is None and incident_like and not summary_reusable_rule:
        reason = "not_reusable_enough"
        rewrite_candidate = memory_store.build_rewrite_candidate(
            summary,
            details,
            inferred_scope,
            normalized_tags,
        )

    existing = None if reason else memory_store.find_existing(inferred_scope, repo, inferred_kind, summary)
    if existing:
        reason = "already_covered"

    response = {
        "accepted": reason is None,
        "reason": reason,
        "scope": inferred_scope,
        "tier": tier,
        "kind": inferred_kind,
        "summary": summary,
        "details": details,
        "tags": normalized_tags,
    }

    if reason is None:
        scope_label = "this repo" if inferred_scope == "repo" else "future work in general"
        response["confirmation_question"] = f'Should I remember "{summary}" for {scope_label}?'
        response["fallback_line"] = f'Memory Suggestion: Remember "{summary}" for {inferred_scope}?'
    elif reason == "not_reusable_enough" and rewrite_candidate:
        response["rewrite_guidance"] = (
            "Rewrite incident-style memories as reusable rules that say what future work should do "
            "using action verbs like Prefer, Guard, Avoid, Use, Do not, or Ensure."
        )
        response["rewrite_candidate"] = rewrite_candidate
    return response


def _list_payload(
    repo_path: str | None = None,
    *,
    scope: str = "all",
    tier: str = "all",
    include_archived: bool = False,
) -> dict[str, Any]:
    _ensure_layout()
    repo = _normalize_repo_path(repo_path)
    entries = memory_store.load_scope_entries(repo, include_all_repos=not repo)
    if tier != "all":
        entries = [entry for entry in entries if entry.tier == tier]
    if scope != "all":
        entries = [entry for entry in entries if entry.scope == scope]
    if not include_archived:
        entries = [entry for entry in entries if entry.status == "active"]
    return {
        "repo_path": repo,
        "scope": scope,
        "tier": tier,
        "include_archived": include_archived,
        "count": len(entries),
        "entries": [_entry_payload(entry) for entry in memory_store.sort_entries(entries)],
    }


def create_server() -> FastMCP:
    server = FastMCP(
        name=SERVER_NAME,
        instructions=(
            "Codex Memory exposes local durable memories as MCP resources and tools. "
            "Use resources for lightweight inspection and tools for recall, search, and memory mutations."
        ),
    )

    @server.resource(
        "memory://overview",
        name="overview",
        description="Overview of the Codex Memory MCP server and its storage layout.",
        mime_type="text/markdown",
    )
    def overview() -> str:
        repositories = _known_repositories()
        repo_lines = [
            f"- `{item['repo_key']}` -> `{item['repo_path']}` ({', '.join(item['tiers'])})"
            for item in repositories
        ]
        if not repo_lines:
            repo_lines = ["- No repo-scoped memories saved yet."]
        return "\n".join(
            [
                "# Codex Memory MCP",
                "",
                f"- Plugin root: `{PLUGIN_ROOT}`",
                f"- Memory root: `{memory_store.MEMORY_ROOT}`",
                "- Static resources: `memory://overview`, `memory://repositories`, `memory://global/core`, `memory://global/semantic`",
                "- Context resources: `memory://context-repositories`, `memory://global/context-repo`, `memory://repo/{repo_key}/context-repo`",
                "- Templates: `memory://repo/{repo_key}/core`, `memory://repo/{repo_key}/semantic`, `memory://repo/{repo_key}/episodic`, `memory://repo/{repo_key}/context-repo`",
                "",
                "## Known Repositories",
                *repo_lines,
            ]
        )

    @server.resource(
        "memory://repositories",
        name="repositories",
        description="Known repo-scoped memory buckets keyed by repo_key.",
        mime_type="application/json",
    )
    def repositories() -> str:
        return _format_json(_known_repositories())

    @server.resource(
        "memory://context-repositories",
        name="context-repositories",
        description="Projected context repositories backed by the local memory store.",
        mime_type="application/json",
    )
    def context_repositories() -> str:
        return _format_json(_known_context_repositories())

    @server.resource(
        "memory://global/core",
        name="global-core",
        description="Global core memories.",
        mime_type="application/json",
    )
    def global_core() -> str:
        return _format_json(_bucket_payload("global", "core"))

    @server.resource(
        "memory://global/semantic",
        name="global-semantic",
        description="Global semantic memories.",
        mime_type="application/json",
    )
    def global_semantic() -> str:
        return _format_json(_bucket_payload("global", "semantic"))

    @server.resource(
        "memory://global/context-repo",
        name="global-context-repo",
        description="Projected global context repository metadata.",
        mime_type="application/json",
    )
    def global_context_repo() -> str:
        return _format_json(memory_store.inspect_context_repository("global"))

    @server.resource(
        "memory://repo/{repo_key}/core",
        name="repo-core",
        description="Repo-scoped core memories for a repo_key.",
        mime_type="application/json",
    )
    def repo_core(repo_key: str) -> str:
        return _format_json(_bucket_payload("repo", "core", repo_key=repo_key))

    @server.resource(
        "memory://repo/{repo_key}/semantic",
        name="repo-semantic",
        description="Repo-scoped semantic memories for a repo_key.",
        mime_type="application/json",
    )
    def repo_semantic(repo_key: str) -> str:
        return _format_json(_bucket_payload("repo", "semantic", repo_key=repo_key))

    @server.resource(
        "memory://repo/{repo_key}/episodic",
        name="repo-episodic",
        description="Repo-scoped episodic memories for a repo_key.",
        mime_type="application/json",
    )
    def repo_episodic(repo_key: str) -> str:
        return _format_json(_bucket_payload("repo", "episodic", repo_key=repo_key))

    @server.resource(
        "memory://repo/{repo_key}/context-repo",
        name="repo-context-repo",
        description="Projected repo-scoped context repository metadata.",
        mime_type="application/json",
    )
    def repo_context_repo(repo_key: str) -> str:
        manifest = memory_store.load_context_manifest("repo", repo_key=repo_key)
        repo_path = manifest.get("repo_path") if manifest else _repo_path_for_key(repo_key)
        if not repo_path:
            raise ValueError(f"Unknown repo_key: {repo_key}")
        return _format_json(memory_store.inspect_context_repository("repo", repo_path))

    @server.tool(
        description="List memories from the local Codex memory store.",
        structured_output=True,
    )
    def list_memories(
        repo_path: str | None = None,
        scope: str = "all",
        tier: str = "all",
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return _list_payload(
            repo_path,
            scope=scope,
            tier=tier,
            include_archived=include_archived,
        )

    @server.tool(
        description="Search memories by text query, optionally prioritizing a repo path.",
        structured_output=True,
    )
    def search_memories(query: str, repo_path: str | None = None, limit: int = 8) -> dict[str, Any]:
        _ensure_layout()
        repo = _normalize_repo_path(repo_path)
        ranked = memory_store.search_candidates(type("Args", (), {"query": query, "repo": repo, "limit": limit})())
        results = [
            {"score": score, "entry": _entry_payload(entry)}
            for score, entry in ranked[:limit]
        ]
        return {
            "query": query,
            "repo_path": repo,
            "count": len(results),
            "results": results,
        }

    @server.tool(
        description="Recall the most relevant memories for a task, optionally scoped to a repo path.",
        structured_output=True,
    )
    def recall_memories(task: str, repo_path: str | None = None, limit: int = 5) -> dict[str, Any]:
        return _recall_payload(task, repo_path=repo_path, limit=limit)

    @server.tool(
        description="Evaluate whether a candidate memory is durable enough to store.",
        structured_output=True,
    )
    def suggest_memory(
        summary: str,
        details: str = "",
        repo_path: str | None = None,
        kind: str | None = None,
        scope: str = "auto",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return _suggest_payload(
            summary,
            details,
            repo_path=repo_path,
            kind=kind,
            scope=scope,
            tags=tags,
        )

    @server.tool(
        description="Save or update a memory entry in the local Codex memory store.",
        structured_output=True,
    )
    def add_memory(
        scope: str,
        kind: str,
        summary: str,
        details: str = "",
        tier: str = "semantic",
        repo_path: str | None = None,
        tags: list[str] | None = None,
        source: str = "user-confirmed",
        confidence: str = "confirmed",
        status: str = "active",
    ) -> dict[str, Any]:
        _ensure_layout()
        repo = _normalize_repo_path(repo_path)
        if scope == "repo" and not repo:
            raise ValueError("repo_path is required for repo-scoped memories.")
        args = type(
            "Args",
            (),
            {
                "scope": scope,
                "tier": tier,
                "repo": repo,
                "kind": kind,
                "summary": summary,
                "details": details,
                "tags": tags or [],
                "source": source,
                "confidence": confidence,
                "status": status,
            },
        )()
        entry = memory_store.build_entry(args)
        path = memory_store.tier_path(entry.tier, entry.scope, repo=entry.repo_path, repo_key=entry.repo_key)
        saved_entry, created = memory_store.upsert_entry(path, entry)
        return {
            "action": "saved" if created else "updated",
            "path": str(path),
            "entry": _entry_payload(saved_entry),
        }

    @server.tool(
        description="Inspect the projected context repository for global or repo-scoped memories.",
        structured_output=True,
    )
    def inspect_context_repo(repo_path: str | None = None) -> dict[str, Any]:
        scope = "repo" if repo_path else "global"
        return memory_store.inspect_context_repository(scope, repo_path)

    @server.tool(
        description="Project current memories into a git-friendly context repository.",
        structured_output=True,
    )
    def sync_context_repo(repo_path: str | None = None) -> dict[str, Any]:
        scope = "repo" if repo_path else "global"
        return memory_store.sync_context_repository(scope, repo_path)

    @server.tool(
        description="Audit context repository health and sizing for the current memory store.",
        structured_output=True,
    )
    def doctor_memory_store(repo_path: str | None = None) -> dict[str, Any]:
        scope = "repo" if repo_path else "global"
        return memory_store.doctor_context_repository(scope, repo_path)

    return server


server = create_server()


if __name__ == "__main__":
    server.run()
