#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


def default_codex_home() -> Path:
    configured = os.environ.get("CODEX_HOME")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".codex"


DEFAULT_MEMORY_ROOT = default_codex_home() / "memories"
MEMORY_ROOT = Path(os.environ.get("CODEX_MEMORY_ROOT", str(DEFAULT_MEMORY_ROOT))).expanduser()

LEGACY_GLOBAL_PATH = MEMORY_ROOT / "global.jsonl"
LEGACY_REPO_ROOT = MEMORY_ROOT / "repos"

CORE_ROOT = MEMORY_ROOT / "core"
CORE_GLOBAL_PATH = CORE_ROOT / "global.json"
CORE_REPO_ROOT = CORE_ROOT / "repos"

SEMANTIC_ROOT = MEMORY_ROOT / "semantic"
SEMANTIC_GLOBAL_PATH = SEMANTIC_ROOT / "global.jsonl"
SEMANTIC_REPO_ROOT = SEMANTIC_ROOT / "repos"

EPISODIC_ROOT = MEMORY_ROOT / "episodic"
EPISODIC_REPO_ROOT = EPISODIC_ROOT / "repos"

CONTEXT_REPO_ROOT = MEMORY_ROOT / "context-repositories"
CONTEXT_GLOBAL_ROOT = CONTEXT_REPO_ROOT / "global"
CONTEXT_REPOS_ROOT = CONTEXT_REPO_ROOT / "repos"

SYSTEM_CONTEXT_KINDS = {
    "preference",
    "workflow",
    "convention",
    "procedure",
    "environment",
    "correction",
}
SYSTEM_CONTEXT_DOC_LIMIT = 20
SYSTEM_CONTEXT_CHAR_LIMIT = 50_000

KIND_CHOICES = (
    "preference",
    "workflow",
    "convention",
    "environment",
    "correction",
    "fact",
    "procedure",
    "lesson",
)
CONFIDENCE_CHOICES = ("confirmed", "high", "medium", "low")
TIER_CHOICES = ("core", "semantic", "episodic")
STATUS_CHOICES = ("active", "archived")
SCOPE_CHOICES = ("global", "repo")
SUGGEST_SCOPE_CHOICES = ("auto", "global", "repo")

SECRET_PATTERNS = (
    "secret",
    "token",
    "password",
    "api key",
    "apikey",
    "credential",
    "private key",
)
ONE_OFF_PATTERNS = (
    "today",
    "tonight",
    "tomorrow",
    "yesterday",
    "temporary",
    "temp",
    "for this task",
    "for this turn",
    "one-off",
    "one off",
    "current branch",
)
INCIDENT_PATTERNS = (
    "bug",
    "failure",
    "failed",
    "incident",
    "debug",
    "error",
    "trace",
    "traced to",
    "postmortem",
    "regression",
)
REUSABLE_RULE_PATTERNS = (
    "prefer",
    "always",
    "never",
    "avoid",
    "guard",
    "use ",
    "do not",
    "don't",
    "should",
    "must",
    "ensure",
    "suppress",
    "centralize",
)
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "how",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "repo",
    "repository",
    "should",
    "task",
    "that",
    "the",
    "this",
    "to",
    "use",
    "we",
    "with",
    "you",
}


@dataclass
class MemoryEntry:
    id: str
    scope: str
    tier: str
    kind: str
    summary: str
    details: str
    tags: list[str] = field(default_factory=list)
    source: str = "user-confirmed"
    confidence: str = "confirmed"
    created_at: str = ""
    updated_at: str = ""
    last_used_at: str | None = None
    use_count: int = 0
    status: str = "active"
    repo_path: str | None = None
    repo_key: str | None = None

    @classmethod
    def from_dict(
        cls,
        payload: dict,
        *,
        tier_override: str | None = None,
        scope_override: str | None = None,
        repo_path_override: str | None = None,
        repo_key_override: str | None = None,
    ) -> "MemoryEntry":
        created_at = payload.get("created_at") or now_iso()
        updated_at = payload.get("updated_at") or created_at
        repo_path = repo_path_override or payload.get("repo_path")
        repo_key = repo_key_override or payload.get("repo_key")
        scope = payload.get("scope") or scope_override or ("repo" if repo_path else "global")
        tier = payload.get("tier") or tier_override or "semantic"
        tags = normalize_tags(payload.get("tags", []))
        return cls(
            id=payload.get("id") or build_memory_id(payload.get("summary", "memory")),
            scope=scope,
            tier=tier,
            kind=payload.get("kind", "fact"),
            summary=payload.get("summary", "").strip(),
            details=payload.get("details", "").strip(),
            tags=tags,
            source=payload.get("source", "user-confirmed"),
            confidence=payload.get("confidence", "confirmed"),
            created_at=created_at,
            updated_at=updated_at,
            last_used_at=payload.get("last_used_at"),
            use_count=int(payload.get("use_count", 0)),
            status=payload.get("status", "active"),
            repo_path=repo_path,
            repo_key=repo_key or (repo_key_for(repo_path) if repo_path else None),
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "scope": self.scope,
            "tier": self.tier,
            "kind": self.kind,
            "summary": self.summary,
            "details": self.details,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "use_count": self.use_count,
            "status": self.status,
        }
        if self.repo_path:
            payload["repo_path"] = self.repo_path
        if self.repo_key:
            payload["repo_key"] = self.repo_key
        return payload


@dataclass
class ContextDocument:
    memory_id: str
    scope: str
    tier: str
    kind: str
    summary: str
    details: str
    relative_path: str
    tags: list[str] = field(default_factory=list)
    source: str = "user-confirmed"
    confidence: str = "confirmed"
    updated_at: str = ""
    last_used_at: str | None = None
    use_count: int = 0
    repo_path: str | None = None
    repo_key: str | None = None

    def to_manifest_item(self) -> dict:
        payload = {
            "memory_id": self.memory_id,
            "scope": self.scope,
            "tier": self.tier,
            "kind": self.kind,
            "summary": self.summary,
            "details": self.details,
            "path": self.relative_path,
            "tags": self.tags,
            "source": self.source,
            "confidence": self.confidence,
            "updated_at": self.updated_at,
            "last_used_at": self.last_used_at,
            "use_count": self.use_count,
        }
        if self.repo_path:
            payload["repo_path"] = self.repo_path
        if self.repo_key:
            payload["repo_key"] = self.repo_key
        return payload


def now_iso() -> str:
    override = os.environ.get("CODEX_MEMORY_NOW")
    if override:
        return override
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower())
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "memory"


def repo_key_for(repo_path: str | None) -> str | None:
    if not repo_path:
        return None
    return slugify(str(Path(repo_path).resolve()))


def build_memory_id(summary: str) -> str:
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{slugify(summary)[:40]}"


def normalize_tags(raw: object) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = []
        for item in raw:
            if isinstance(item, str):
                parts.extend(item.split(","))
    tags: list[str] = []
    for part in parts:
        tag = slugify(part.strip())
        if tag and tag not in tags:
            tags.append(tag)
    return tags


def tokenize_query(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9._/-]*", text.lower())
    return [word for word in words if word not in STOPWORDS and len(word) > 1]


def core_path(scope: str, repo: str | None = None, repo_key: str | None = None) -> Path:
    if scope == "global":
        return CORE_GLOBAL_PATH
    resolved_key = repo_key or repo_key_for(repo)
    if not resolved_key:
        raise ValueError("A repo path is required for repo-scoped core memory.")
    return CORE_REPO_ROOT / f"{resolved_key}.json"


def tier_path(tier: str, scope: str, repo: str | None = None, repo_key: str | None = None) -> Path:
    if tier == "core":
        return core_path(scope, repo=repo, repo_key=repo_key)
    if scope == "global":
        if tier == "semantic":
            return SEMANTIC_GLOBAL_PATH
        raise ValueError("Global episodic memory is not supported.")
    resolved_key = repo_key or repo_key_for(repo)
    if not resolved_key:
        raise ValueError("A repo path is required for repo-scoped memory.")
    if tier == "semantic":
        return SEMANTIC_REPO_ROOT / f"{resolved_key}.jsonl"
    if tier == "episodic":
        return EPISODIC_REPO_ROOT / f"{resolved_key}.jsonl"
    raise ValueError(f"Unsupported tier: {tier}")


def context_repo_path(scope: str, repo: str | None = None, repo_key: str | None = None) -> Path:
    if scope == "global":
        return CONTEXT_GLOBAL_ROOT
    resolved_key = repo_key or repo_key_for(repo)
    if not resolved_key:
        raise ValueError("A repo path is required for a repo-scoped context repository.")
    return CONTEXT_REPOS_ROOT / resolved_key


def context_manifest_path(scope: str, repo: str | None = None, repo_key: str | None = None) -> Path:
    return context_repo_path(scope, repo=repo, repo_key=repo_key) / "manifest.json"


def context_readme_path(scope: str, repo: str | None = None, repo_key: str | None = None) -> Path:
    return context_repo_path(scope, repo=repo, repo_key=repo_key) / "README.md"


def context_section_for(entry: MemoryEntry) -> Path:
    if entry.tier == "core":
        return Path("system") / "core"
    if entry.tier == "episodic" or entry.kind == "lesson":
        return Path("episodes") / entry.kind
    if entry.kind in SYSTEM_CONTEXT_KINDS:
        return Path("system") / entry.kind
    return Path("knowledge") / entry.kind


def context_relative_path(entry: MemoryEntry) -> str:
    filename = f"{slugify(entry.summary)}.md"
    return (context_section_for(entry) / filename).as_posix()


def load_global_entries() -> list[MemoryEntry]:
    entries: list[MemoryEntry] = []
    entries.extend(load_tier_entries("core", "global"))
    entries.extend(load_tier_entries("semantic", "global"))
    return sort_entries(entries)


def scope_entries(scope: str, repo: str | None = None) -> list[MemoryEntry]:
    if scope == "global":
        return load_global_entries()
    if not repo:
        raise ValueError("A repo path is required for repo-scoped entries.")
    return [entry for entry in load_scope_entries(repo, include_all_repos=False) if entry.scope == "repo"]


def ensure_layout() -> None:
    MEMORY_ROOT.mkdir(parents=True, exist_ok=True)
    CORE_REPO_ROOT.mkdir(parents=True, exist_ok=True)
    SEMANTIC_REPO_ROOT.mkdir(parents=True, exist_ok=True)
    EPISODIC_REPO_ROOT.mkdir(parents=True, exist_ok=True)
    CONTEXT_GLOBAL_ROOT.mkdir(parents=True, exist_ok=True)
    CONTEXT_REPOS_ROOT.mkdir(parents=True, exist_ok=True)
    migrate_legacy_memories()


def read_jsonl(path: Path) -> list[MemoryEntry]:
    if not path.exists():
        return []
    entries: list[MemoryEntry] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            raw = line.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL in {path} at line {line_number}: {exc}") from exc
            entries.append(MemoryEntry.from_dict(payload))
    return entries


def write_jsonl(path: Path, entries: Iterable[MemoryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for entry in sort_entries(entries):
            handle.write(json.dumps(entry.to_dict(), ensure_ascii=True))
            handle.write("\n")


def read_json_array(path: Path) -> list[MemoryEntry]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{path} must contain a JSON array.")
    return [MemoryEntry.from_dict(item, tier_override="core") for item in payload]


def write_json_array(path: Path, entries: Iterable[MemoryEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [entry.to_dict() for entry in sort_entries(entries)]
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def load_entries(path: Path, *, tier_override: str | None = None) -> list[MemoryEntry]:
    if path.suffix == ".json":
        return read_json_array(path)
    return [
        MemoryEntry.from_dict(entry.to_dict(), tier_override=tier_override or entry.tier)
        for entry in read_jsonl(path)
    ]


def write_entries(path: Path, entries: Iterable[MemoryEntry]) -> None:
    if path.suffix == ".json":
        write_json_array(path, entries)
        return
    write_jsonl(path, entries)


def sort_entries(entries: Iterable[MemoryEntry]) -> list[MemoryEntry]:
    return sorted(
        entries,
        key=lambda entry: (
            entry.status != "active",
            entry.tier,
            entry.kind,
            entry.summary.lower(),
        ),
    )


def entry_identity(entry: MemoryEntry) -> tuple[str, str, str, str]:
    repo_marker = entry.repo_key or ""
    return (entry.tier, entry.kind, entry.summary.strip().lower(), repo_marker)


def merge_entries(existing: list[MemoryEntry], additions: list[MemoryEntry]) -> list[MemoryEntry]:
    merged: dict[tuple[str, str, str, str], MemoryEntry] = {
        entry_identity(entry): entry for entry in existing
    }
    for addition in additions:
        key = entry_identity(addition)
        current = merged.get(key)
        if current is None:
            merged[key] = addition
            continue
        if current.id == addition.id or current.updated_at <= addition.updated_at:
            merged[key] = addition
    return sort_entries(merged.values())


def migrate_legacy_memories() -> None:
    migrated_global = migrate_legacy_file(
        LEGACY_GLOBAL_PATH,
        scope="global",
        target=SEMANTIC_GLOBAL_PATH,
        repo_path=None,
        repo_key=None,
    )
    if LEGACY_REPO_ROOT.exists():
        for path in sorted(LEGACY_REPO_ROOT.glob("*.jsonl")):
            repo_entries = read_jsonl(path)
            if not repo_entries:
                continue
            repo_path = repo_entries[0].repo_path
            repo_key = repo_entries[0].repo_key or path.stem
            migrate_legacy_file(
                path,
                scope="repo",
                target=SEMANTIC_REPO_ROOT / f"{repo_key}.jsonl",
                repo_path=repo_path,
                repo_key=repo_key,
            )
    if migrated_global and not CORE_GLOBAL_PATH.exists():
        write_json_array(CORE_GLOBAL_PATH, [])


def migrate_legacy_file(
    source_path: Path,
    *,
    scope: str,
    target: Path,
    repo_path: str | None,
    repo_key: str | None,
) -> bool:
    if not source_path.exists():
        return False
    raw_entries = read_jsonl(source_path)
    if not raw_entries:
        return False
    migrated = [
        MemoryEntry.from_dict(
            entry.to_dict(),
            tier_override="semantic",
            scope_override=scope,
            repo_path_override=repo_path or entry.repo_path,
            repo_key_override=repo_key or entry.repo_key,
        )
        for entry in raw_entries
    ]
    existing = load_entries(target) if target.exists() else []
    write_entries(target, merge_entries(existing, migrated))
    return True


def active_entries(entries: Iterable[MemoryEntry]) -> list[MemoryEntry]:
    return [entry for entry in entries if entry.status == "active"]


def load_tier_entries(tier: str, scope: str, repo: str | None = None) -> list[MemoryEntry]:
    path = tier_path(tier, scope, repo)
    return active_entries(load_entries(path)) if path.exists() else []


def load_scope_entries(repo: str | None = None, *, include_all_repos: bool = False) -> list[MemoryEntry]:
    entries: list[MemoryEntry] = []
    entries.extend(load_tier_entries("core", "global"))
    entries.extend(load_tier_entries("semantic", "global"))
    if repo:
        entries.extend(load_tier_entries("core", "repo", repo))
        entries.extend(load_tier_entries("semantic", "repo", repo))
        entries.extend(load_tier_entries("episodic", "repo", repo))
    elif include_all_repos:
        for root in (CORE_REPO_ROOT, SEMANTIC_REPO_ROOT, EPISODIC_REPO_ROOT):
            pattern = "*.json" if root is CORE_REPO_ROOT else "*.jsonl"
            for path in sorted(root.glob(pattern)):
                entries.extend(active_entries(load_entries(path)))
    return sort_entries(entries)


def build_context_document(entry: MemoryEntry) -> ContextDocument:
    return ContextDocument(
        memory_id=entry.id,
        scope=entry.scope,
        tier=entry.tier,
        kind=entry.kind,
        summary=entry.summary,
        details=entry.details,
        relative_path=context_relative_path(entry),
        tags=entry.tags,
        source=entry.source,
        confidence=entry.confidence,
        updated_at=entry.updated_at,
        last_used_at=entry.last_used_at,
        use_count=entry.use_count,
        repo_path=entry.repo_path,
        repo_key=entry.repo_key,
    )


def json_scalar(value: object) -> str:
    return json.dumps(value, ensure_ascii=True)


def render_context_document(document: ContextDocument) -> str:
    lines = [
        "---",
        f"id: {json_scalar(document.memory_id)}",
        f"summary: {json_scalar(document.summary)}",
        f"scope: {json_scalar(document.scope)}",
        f"tier: {json_scalar(document.tier)}",
        f"kind: {json_scalar(document.kind)}",
        f"tags: {json_scalar(document.tags)}",
        f"source: {json_scalar(document.source)}",
        f"confidence: {json_scalar(document.confidence)}",
        f"updated_at: {json_scalar(document.updated_at)}",
        f"last_used_at: {json_scalar(document.last_used_at)}",
        f"use_count: {document.use_count}",
        f"repo_path: {json_scalar(document.repo_path)}",
        f"repo_key: {json_scalar(document.repo_key)}",
        "---",
        "",
        f"# {document.summary}",
        "",
    ]
    body = document.details.strip() or document.summary
    lines.append(body)
    lines.extend(
        [
            "",
            "## Guidance",
            "",
            f"- Scope: `{document.scope}`",
            f"- Tier: `{document.tier}`",
            f"- Kind: `{document.kind}`",
        ]
    )
    if document.tags:
        lines.append(f"- Tags: `{', '.join(document.tags)}`")
    if document.repo_path:
        lines.append(f"- Repo Path: `{document.repo_path}`")
    if document.last_used_at:
        lines.append(f"- Last Used: `{document.last_used_at}`")
    lines.append("")
    return "\n".join(lines)


def render_context_readme(
    scope: str,
    *,
    repo: str | None,
    repo_key: str | None,
    documents: list[ContextDocument],
    imports: list[dict[str, object]],
) -> str:
    title = "Global Context Repository" if scope == "global" else "Repo Context Repository"
    lines = [
        f"# {title}",
        "",
        "This directory is a git-friendly projection of the Codex Memory store.",
        "It keeps durable context in small Markdown files so agents can inspect, diff, and selectively load it.",
        "",
        "## Layout",
        "",
        "- `system/`: always-on or high-signal instructions such as preferences, workflows, and conventions.",
        "- `knowledge/`: reusable facts and procedures that are worth retrieving on demand.",
        "- `episodes/`: incident-style lessons with weaker default recall.",
        "- `manifest.json`: machine-readable index for MCP tools and audits.",
        "",
        "## Summary",
        "",
        f"- Scope: `{scope}`",
        f"- Documents: `{len(documents)}`",
    ]
    if repo_key:
        lines.append(f"- Repo Key: `{repo_key}`")
    if repo:
        lines.append(f"- Repo Path: `{repo}`")
    if imports:
        lines.extend(["", "## Linked Contexts", ""])
        for item in imports:
            lines.append(f"- `{item['scope']}` -> `{item['root']}`")
    lines.append("")
    return "\n".join(lines)


def load_context_manifest(scope: str, repo: str | None = None, repo_key: str | None = None) -> dict | None:
    path = context_manifest_path(scope, repo=repo, repo_key=repo_key)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def context_imports(scope: str) -> list[dict[str, object]]:
    if scope != "repo":
        return []
    global_root = context_repo_path("global")
    global_manifest = context_manifest_path("global")
    return [
        {
            "scope": "global",
            "root": str(global_root),
            "manifest_path": str(global_manifest),
            "exists": global_manifest.exists(),
        }
    ]


def context_repo_tree(root: Path) -> list[str]:
    if not root.exists():
        return []
    return sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())


def context_counts(documents: list[ContextDocument]) -> dict[str, dict[str, int]]:
    tier_counts: dict[str, int] = {}
    kind_counts: dict[str, int] = {}
    section_counts: dict[str, int] = {}
    for document in documents:
        tier_counts[document.tier] = tier_counts.get(document.tier, 0) + 1
        kind_counts[document.kind] = kind_counts.get(document.kind, 0) + 1
        section = document.relative_path.split("/", 1)[0]
        section_counts[section] = section_counts.get(section, 0) + 1
    return {
        "tiers": dict(sorted(tier_counts.items())),
        "kinds": dict(sorted(kind_counts.items())),
        "sections": dict(sorted(section_counts.items())),
    }


def sync_context_repository(scope: str, repo: str | None = None) -> dict:
    ensure_layout()
    normalized_repo = str(Path(repo).resolve()) if repo else None
    repo_key = repo_key_for(normalized_repo)
    root = context_repo_path(scope, repo=normalized_repo, repo_key=repo_key)
    root.mkdir(parents=True, exist_ok=True)

    entries = scope_entries(scope, normalized_repo)
    documents = [build_context_document(entry) for entry in entries]
    imports = context_imports(scope)

    previous_manifest = load_context_manifest(scope, normalized_repo, repo_key)
    previous_paths = {
        item["path"]
        for item in previous_manifest.get("documents", [])
    } if previous_manifest else set()
    current_paths = {document.relative_path for document in documents}

    for stale_path in sorted(previous_paths - current_paths):
        candidate = root / Path(stale_path)
        if candidate.exists() and candidate.is_file():
            candidate.unlink()

    for document in documents:
        path = root / Path(document.relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_context_document(document), encoding="utf-8")

    readme = render_context_readme(
        scope,
        repo=normalized_repo,
        repo_key=repo_key,
        documents=documents,
        imports=imports,
    )
    context_readme_path(scope, normalized_repo, repo_key).write_text(readme, encoding="utf-8")

    manifest = {
        "generated_at": now_iso(),
        "scope": scope,
        "repo_path": normalized_repo,
        "repo_key": repo_key,
        "root": str(root),
        "manifest_path": str(context_manifest_path(scope, normalized_repo, repo_key)),
        "readme_path": str(context_readme_path(scope, normalized_repo, repo_key)),
        "imports": imports,
        "counts": context_counts(documents),
        "documents": [document.to_manifest_item() for document in documents],
    }
    context_manifest_path(scope, normalized_repo, repo_key).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def inspect_context_repository(scope: str, repo: str | None = None) -> dict:
    ensure_layout()
    normalized_repo = str(Path(repo).resolve()) if repo else None
    repo_key = repo_key_for(normalized_repo)
    root = context_repo_path(scope, repo=normalized_repo, repo_key=repo_key)
    documents = [build_context_document(entry) for entry in scope_entries(scope, normalized_repo)]
    manifest = load_context_manifest(scope, normalized_repo, repo_key)
    return {
        "scope": scope,
        "repo_path": normalized_repo,
        "repo_key": repo_key,
        "root": str(root),
        "exists": root.exists(),
        "manifest_exists": context_manifest_path(scope, normalized_repo, repo_key).exists(),
        "readme_exists": context_readme_path(scope, normalized_repo, repo_key).exists(),
        "imports": context_imports(scope),
        "counts": context_counts(documents),
        "documents": [document.to_manifest_item() for document in documents],
        "synced_document_count": len(manifest.get("documents", [])) if manifest else 0,
        "tree": context_repo_tree(root),
    }


def doctor_context_repository(scope: str, repo: str | None = None) -> dict:
    ensure_layout()
    normalized_repo = str(Path(repo).resolve()) if repo else None
    repo_key = repo_key_for(normalized_repo)
    root = context_repo_path(scope, repo=normalized_repo, repo_key=repo_key)
    manifest = load_context_manifest(scope, normalized_repo, repo_key) or {}
    expected_documents = [build_context_document(entry) for entry in scope_entries(scope, normalized_repo)]
    expected_paths = {document.relative_path for document in expected_documents}
    manifest_paths = {item["path"] for item in manifest.get("documents", [])}
    disk_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*.md")
    } if root.exists() else set()
    disk_paths.discard("README.md")

    issues: list[dict[str, object]] = []

    def add_issue(code: str, severity: str, message: str, *, paths: list[str] | None = None) -> None:
        payload: dict[str, object] = {
            "code": code,
            "severity": severity,
            "message": message,
        }
        if paths:
            payload["paths"] = paths
        issues.append(payload)

    if not root.exists():
        add_issue("missing_root", "warning", "Context repository root has not been initialized.")
    if not manifest:
        add_issue("missing_manifest", "warning", "Context repository manifest is missing. Run sync-context.")

    missing_on_disk = sorted(expected_paths - disk_paths)
    if missing_on_disk:
        add_issue(
            "missing_documents",
            "warning",
            "Context documents expected from the memory store are missing on disk.",
            paths=missing_on_disk,
        )

    missing_in_manifest = sorted(expected_paths - manifest_paths)
    if missing_in_manifest:
        add_issue(
            "manifest_missing_documents",
            "warning",
            "Manifest is missing projected context documents.",
            paths=missing_in_manifest,
        )

    stale_manifest_paths = sorted(manifest_paths - expected_paths)
    if stale_manifest_paths:
        add_issue(
            "stale_manifest_entries",
            "warning",
            "Manifest references documents that are no longer projected from active memories.",
            paths=stale_manifest_paths,
        )

    orphan_docs = sorted(disk_paths - expected_paths)
    if orphan_docs:
        add_issue(
            "orphan_documents",
            "info",
            "Context repository contains Markdown files that are not projected from active memories.",
            paths=orphan_docs,
        )

    summary_map: dict[str, list[str]] = {}
    system_chars = 0
    system_docs = 0
    for document in expected_documents:
        summary_map.setdefault(document.summary.strip().lower(), []).append(document.relative_path)
        if document.relative_path.startswith("system/"):
            system_docs += 1
            system_chars += len(render_context_document(document))

    duplicate_paths = sorted(
        path
        for paths in summary_map.values()
        if len(paths) > 1
        for path in paths
    )
    if duplicate_paths:
        add_issue(
            "duplicate_summaries",
            "warning",
            "Multiple active memories collapse to the same summary. Consider merging or renaming them.",
            paths=duplicate_paths,
        )

    if system_docs > SYSTEM_CONTEXT_DOC_LIMIT:
        add_issue(
            "system_context_doc_limit",
            "warning",
            (
                "System-context document count exceeds the recommended limit for always-on guidance. "
                f"Found {system_docs}, recommended <= {SYSTEM_CONTEXT_DOC_LIMIT}."
            ),
        )

    if system_chars > SYSTEM_CONTEXT_CHAR_LIMIT:
        add_issue(
            "system_context_char_limit",
            "warning",
            (
                "System-context document size exceeds the recommended limit for in-context guidance. "
                f"Found {system_chars} chars, recommended <= {SYSTEM_CONTEXT_CHAR_LIMIT}."
            ),
        )

    return {
        "scope": scope,
        "repo_path": normalized_repo,
        "repo_key": repo_key,
        "root": str(root),
        "healthy": not any(issue["severity"] == "warning" for issue in issues),
        "issue_count": len(issues),
        "issues": issues,
        "counts": context_counts(expected_documents),
        "expected_document_count": len(expected_documents),
        "disk_document_count": len(disk_paths),
        "manifest_document_count": len(manifest.get("documents", [])),
    }


def score_entry(entry: MemoryEntry, query_terms: list[str], repo_key: str | None) -> int:
    summary_text = entry.summary.lower()
    detail_text = entry.details.lower()
    kind_text = entry.kind.lower()
    tags_text = " ".join(entry.tags)
    score = 0
    for term in query_terms:
        if term in summary_text:
            score += 5
        if term in detail_text:
            score += 2
        if term in tags_text:
            score += 3
        if term == kind_text:
            score += 1
    if repo_key and entry.repo_key == repo_key:
        score += 5
    if entry.scope == "global" and entry.kind == "preference":
        score += 1
    if entry.confidence == "confirmed":
        score += 2
    elif entry.confidence == "high":
        score += 1
    score += min(entry.use_count, 2)
    return score


def matched_terms(entry: MemoryEntry, query_terms: list[str]) -> int:
    summary_text = entry.summary.lower()
    detail_text = entry.details.lower()
    tags_text = " ".join(entry.tags)
    hits = 0
    for term in query_terms:
        if term in summary_text or term in detail_text or term in tags_text:
            hits += 1
    return hits


def touch_entries(entries: list[MemoryEntry]) -> None:
    if not entries:
        return
    now = now_iso()
    grouped: dict[Path, list[MemoryEntry]] = {}
    for entry in entries:
        path = tier_path(entry.tier, entry.scope, repo=entry.repo_path, repo_key=entry.repo_key)
        grouped.setdefault(path, [])
    for path in grouped:
        persisted = load_entries(path)
        changed = False
        for persisted_entry in persisted:
            for surfaced_entry in entries:
                if persisted_entry.id != surfaced_entry.id:
                    continue
                persisted_entry.last_used_at = now
                persisted_entry.use_count += 1
                persisted_entry.updated_at = now
                changed = True
        if changed:
            write_entries(path, persisted)


def format_entry(entry: MemoryEntry) -> str:
    scope = entry.scope
    if entry.repo_key:
        scope = f"{scope}:{entry.repo_key}"
    detail = f" | {entry.details}" if entry.details else ""
    tags = f" | tags={','.join(entry.tags)}" if entry.tags else ""
    return f"- [{entry.tier}/{entry.kind}] {entry.summary} ({scope}, {entry.confidence}){detail}{tags}"


def print_section(title: str, entries: list[MemoryEntry]) -> None:
    if not entries:
        return
    print(f"{title}:")
    for entry in entries:
        print(format_entry(entry))


def build_entry(args: argparse.Namespace) -> MemoryEntry:
    repo_path = str(Path(args.repo).resolve()) if args.scope == "repo" else None
    repo_key = repo_key_for(repo_path)
    if args.tier == "episodic" and args.scope != "repo":
        raise ValueError("Episodic memories must be repo-scoped.")
    timestamp = now_iso()
    return MemoryEntry(
        id=build_memory_id(args.summary),
        scope=args.scope,
        tier=args.tier,
        kind=args.kind,
        summary=args.summary.strip(),
        details=args.details.strip(),
        tags=normalize_tags(args.tags),
        source=args.source.strip(),
        confidence=args.confidence,
        created_at=timestamp,
        updated_at=timestamp,
        last_used_at=None,
        use_count=0,
        status=args.status,
        repo_path=repo_path,
        repo_key=repo_key,
    )


def upsert_entry(path: Path, new_entry: MemoryEntry) -> tuple[MemoryEntry, bool]:
    existing = load_entries(path) if path.exists() else []
    key = entry_identity(new_entry)
    for index, entry in enumerate(existing):
        if entry.id == new_entry.id or entry_identity(entry) == key:
            new_entry.id = entry.id
            new_entry.created_at = entry.created_at
            existing[index] = new_entry
            write_entries(path, existing)
            return new_entry, False
    existing.append(new_entry)
    write_entries(path, existing)
    return new_entry, True


def cmd_add(args: argparse.Namespace) -> int:
    ensure_layout()
    entry = build_entry(args)
    path = tier_path(entry.tier, entry.scope, repo=entry.repo_path, repo_key=entry.repo_key)
    saved_entry, created = upsert_entry(path, entry)
    action = "saved" if created else "updated"
    print(f"{action}: {saved_entry.summary}")
    print(f"path: {path}")
    return 0


def search_candidates(args: argparse.Namespace) -> list[tuple[int, MemoryEntry]]:
    terms = tokenize_query(args.query)
    repo_key = repo_key_for(args.repo) if getattr(args, "repo", None) else None
    entries = load_scope_entries(args.repo, include_all_repos=not getattr(args, "repo", None))
    ranked = [(score_entry(entry, terms, repo_key), entry) for entry in entries]
    ranked = [item for item in ranked if item[0] > 0]
    ranked.sort(key=lambda item: (-item[0], item[1].summary.lower()))
    return ranked


def cmd_search(args: argparse.Namespace) -> int:
    ensure_layout()
    ranked = search_candidates(args)
    if not ranked:
        print("No matching memories found.")
        return 0
    for _, entry in ranked[: args.limit]:
        print(format_entry(entry))
    return 0


def select_semantic(entries: list[MemoryEntry], terms: list[str], repo_key: str | None, limit: int) -> list[MemoryEntry]:
    ranked = [(score_entry(entry, terms, repo_key), entry) for entry in entries]
    ranked = [item for item in ranked if item[0] > 0]
    ranked.sort(key=lambda item: (-item[0], item[1].summary.lower()))
    return [entry for _, entry in ranked[:limit]]


def select_episodic(entries: list[MemoryEntry], terms: list[str], repo_key: str | None, limit: int) -> list[MemoryEntry]:
    ranked = [
        (score_entry(entry, terms, repo_key), matched_terms(entry, terms), entry)
        for entry in entries
    ]
    ranked = [item for item in ranked if item[0] >= 7 and item[1] >= 2]
    ranked.sort(key=lambda item: (-item[0], item[2].summary.lower()))
    return [entry for _, _, entry in ranked[:limit]]


def cmd_recall(args: argparse.Namespace) -> int:
    ensure_layout()
    repo = str(Path(args.repo).resolve()) if args.repo else None
    terms = tokenize_query(args.task)
    repo_key = repo_key_for(repo)

    core_entries = load_tier_entries("core", "global")
    semantic_entries = load_tier_entries("semantic", "global")
    episodic_entries: list[MemoryEntry] = []

    if repo:
        core_entries.extend(load_tier_entries("core", "repo", repo))
        semantic_entries.extend(load_tier_entries("semantic", "repo", repo))
        episodic_entries.extend(load_tier_entries("episodic", "repo", repo))

    semantic_hits = select_semantic(semantic_entries, terms, repo_key, limit=max(args.limit - len(core_entries), 0))
    episodic_hits = select_episodic(episodic_entries, terms, repo_key, limit=min(2, args.limit))

    surfaced = sort_entries(core_entries) + semantic_hits + episodic_hits
    if not surfaced:
        print("No applicable memories found.")
        return 0

    print_section("Core memories", sort_entries(core_entries))
    print_section("Relevant semantic memories", semantic_hits)
    print_section("Relevant episodic memories", episodic_hits)
    touch_entries(surfaced)
    return 0


def infer_kind(summary: str, details: str) -> str:
    text = f"{summary} {details}".lower()
    if any(term in text for term in ("prefer", "preference", "tone", "concise", "verbose", "style")):
        return "preference"
    if any(term in text for term in ("build", "test", "workflow", "command", "steps", "always run")):
        return "workflow"
    if any(term in text for term in ("convention", "naming", "use bun", "use cargo", "architecture")):
        return "convention"
    if any(term in text for term in ("failed", "failure", "incident", "debug", "bug", "error")):
        return "lesson"
    return "fact"


def infer_scope(kind: str, repo: str | None, summary: str, details: str) -> str:
    if not repo:
        return "global"
    text = f"{summary} {details}".lower()
    if kind == "preference" and not any(term in text for term in ("repo", "build", "test", "package", "tool")):
        return "global"
    return "repo"


def infer_tier(kind: str, summary: str, details: str, scope: str) -> str:
    text = f"{summary} {details}".lower()
    if scope == "repo" and any(term in text for term in ("failed", "failure", "debug", "incident", "bug", "error")):
        return "episodic"
    return "semantic"


def normalize_sentence(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip(" .;:-")
    if not cleaned:
        return ""
    return cleaned[0].upper() + cleaned[1:]


def extract_rule_clause(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ""
    segments = re.split(r"(?<=[.;])\s+|\n+", normalized)
    for segment in segments:
        candidate = segment.strip(" .;:")
        if candidate and any(pattern in candidate.lower() for pattern in REUSABLE_RULE_PATTERNS):
            return normalize_sentence(candidate)
    return ""


def rewrite_incident_summary(summary: str, details: str) -> str:
    summary_clean = normalize_sentence(summary)
    summary_lower = summary_clean.lower()
    match = re.match(r"(.+?) can come from (.+)", summary_lower)
    if match:
        subject = normalize_sentence(match.group(1))
        cause = match.group(2).strip(" .")
        return normalize_sentence(f"Prevent {subject.lower()} by guarding {cause}")
    rule_clause = extract_rule_clause(details) or extract_rule_clause(summary)
    if rule_clause:
        if len(rule_clause) <= 96:
            return rule_clause
        shortened = re.split(r"\band\b|\bwhile\b|,", rule_clause, maxsplit=1)[0].strip()
        if shortened:
            return normalize_sentence(shortened)
    return summary_clean


def build_rewrite_candidate(summary: str, details: str, scope: str, tags: list[str]) -> dict | None:
    rule_details = extract_rule_clause(details)
    rewritten_summary = rewrite_incident_summary(summary, details)
    if not rewritten_summary or rewritten_summary.strip().lower() == normalize_sentence(summary).strip().lower():
        return None
    rewritten_details = rule_details or details.strip()
    return {
        "scope": scope,
        "tier": "semantic",
        "kind": "convention",
        "summary": rewritten_summary,
        "details": rewritten_details,
        "tags": tags,
    }


def find_existing(scope: str, repo: str | None, kind: str, summary: str) -> MemoryEntry | None:
    entries = load_scope_entries(repo, include_all_repos=False)
    summary_key = summary.strip().lower()
    for entry in entries:
        if entry.scope != scope:
            continue
        if kind != entry.kind:
            continue
        if entry.summary.strip().lower() == summary_key and entry.status == "active":
            return entry
    return None


def cmd_suggest(args: argparse.Namespace) -> int:
    ensure_layout()
    summary = args.summary.strip()
    details = args.details.strip()
    summary_text = summary.lower()
    details_text = details.lower()
    text = f"{summary} {details}".lower()

    reason = None
    if not summary or len(summary) < 8:
        reason = "summary_too_short"
    elif any(pattern in text for pattern in SECRET_PATTERNS):
        reason = "contains_secret_like_content"
    elif any(pattern in text for pattern in ONE_OFF_PATTERNS) or re.search(r"(?:#\d+|\bpr\s*\d+\b|\bissue\s*\d+\b)", text):
        reason = "looks_one_off"

    kind = args.kind or infer_kind(summary, details)
    scope = args.scope if args.scope != "auto" else infer_scope(kind, args.repo, summary, details)
    tier = infer_tier(kind, summary, details, scope)
    incident_like = any(pattern in text for pattern in INCIDENT_PATTERNS) or kind == "lesson" or tier == "episodic"
    summary_reusable_rule = any(pattern in summary_text for pattern in REUSABLE_RULE_PATTERNS)
    tags = normalize_tags(args.tags)
    rewrite_candidate = None
    if reason is None and incident_like and not summary_reusable_rule:
        reason = "not_reusable_enough"
        rewrite_candidate = build_rewrite_candidate(summary, details, scope, tags)
    existing = None if reason else find_existing(scope, args.repo, kind, summary)
    if existing:
        reason = "already_covered"

    response = {
        "accepted": reason is None,
        "reason": reason,
        "scope": scope,
        "tier": tier,
        "kind": kind,
        "summary": summary,
        "details": details,
        "tags": tags,
    }

    if reason is None:
        scope_label = "this repo" if scope == "repo" else "future work in general"
        response["confirmation_question"] = f'Should I remember "{summary}" for {scope_label}?'
        response["fallback_line"] = f'Memory Suggestion: Remember "{summary}" for {scope}?'
    elif reason == "not_reusable_enough" and rewrite_candidate:
        response["rewrite_guidance"] = (
            "Rewrite incident-style memories as reusable rules that say what future work should do "
            "using action verbs like Prefer, Guard, Avoid, Use, Do not, or Ensure."
        )
        response["rewrite_candidate"] = rewrite_candidate
    print(json.dumps(response, indent=2))
    return 0


def find_entry_by_id(memory_id: str) -> tuple[Path, list[MemoryEntry], MemoryEntry] | None:
    paths: list[Path] = [CORE_GLOBAL_PATH, SEMANTIC_GLOBAL_PATH]
    paths.extend(sorted(CORE_REPO_ROOT.glob("*.json")))
    paths.extend(sorted(SEMANTIC_REPO_ROOT.glob("*.jsonl")))
    paths.extend(sorted(EPISODIC_REPO_ROOT.glob("*.jsonl")))
    for path in paths:
        if not path.exists():
            continue
        entries = load_entries(path)
        for entry in entries:
            if entry.id == memory_id:
                return path, entries, entry
    return None


def remove_entry(entries: list[MemoryEntry], memory_id: str) -> list[MemoryEntry]:
    return [entry for entry in entries if entry.id != memory_id]


def cmd_promote_core(args: argparse.Namespace) -> int:
    ensure_layout()
    found = find_entry_by_id(args.id)
    if not found:
        print("Memory not found.")
        return 1
    source_path, source_entries, entry = found
    if entry.tier == "core":
        print("Memory is already in core.")
        return 0
    updated = MemoryEntry.from_dict(entry.to_dict(), tier_override="core")
    updated.tier = "core"
    updated.updated_at = now_iso()
    target = tier_path("core", entry.scope, repo=entry.repo_path, repo_key=entry.repo_key)
    upserted, _ = upsert_entry(target, updated)
    write_entries(source_path, remove_entry(source_entries, entry.id))
    print(f"promoted: {upserted.summary}")
    print(f"path: {target}")
    return 0


def cmd_demote_core(args: argparse.Namespace) -> int:
    ensure_layout()
    found = find_entry_by_id(args.id)
    if not found:
        print("Memory not found.")
        return 1
    source_path, source_entries, entry = found
    if entry.tier != "core":
        print("Memory is not in core.")
        return 1
    updated = MemoryEntry.from_dict(entry.to_dict(), tier_override="semantic")
    updated.tier = "semantic"
    updated.updated_at = now_iso()
    target = tier_path("semantic", entry.scope, repo=entry.repo_path, repo_key=entry.repo_key)
    upserted, _ = upsert_entry(target, updated)
    write_entries(source_path, remove_entry(source_entries, entry.id))
    print(f"demoted: {upserted.summary}")
    print(f"path: {target}")
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    ensure_layout()
    entries: list[MemoryEntry] = []
    if args.repo:
        repo = str(Path(args.repo).resolve())
        entries.extend(load_scope_entries(repo, include_all_repos=False))
    else:
        entries.extend(load_scope_entries(include_all_repos=True))
    if args.tier != "all":
        entries = [entry for entry in entries if entry.tier == args.tier]
    if args.scope != "all":
        entries = [entry for entry in entries if entry.scope == args.scope]
    if not args.include_archived:
        entries = [entry for entry in entries if entry.status == "active"]
    if not entries:
        print("No memories saved.")
        return 0
    for entry in sort_entries(entries):
        print(format_entry(entry))
    return 0


def cmd_export_agents(args: argparse.Namespace) -> int:
    ensure_layout()
    repo = str(Path(args.repo).resolve())
    core_entries = load_tier_entries("core", "repo", repo)
    if not core_entries:
        semantic_entries = [
            entry
            for entry in load_tier_entries("semantic", "repo", repo)
            if entry.confidence in {"confirmed", "high"}
        ]
        entries = semantic_entries
    else:
        entries = core_entries
    if not entries:
        print("No repo memories saved.")
        return 0
    print("## Codex Memory")
    print("The following durable repo memories were promoted from the local memory store:")
    for entry in sort_entries(entries):
        line = f"- {entry.summary}"
        if entry.details:
            line = f"{line}; {entry.details}"
        print(line)
    return 0


def cmd_sync_context(args: argparse.Namespace) -> int:
    scope = "repo" if args.repo else "global"
    payload = sync_context_repository(scope, args.repo)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_inspect_context(args: argparse.Namespace) -> int:
    scope = "repo" if args.repo else "global"
    payload = inspect_context_repository(scope, args.repo)
    print(json.dumps(payload, indent=2))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    scope = "repo" if args.repo else "global"
    payload = doctor_context_repository(scope, args.repo)
    print(json.dumps(payload, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=f"Manage Codex memories stored under {MEMORY_ROOT}."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add or update a memory entry.")
    add_parser.add_argument("--scope", choices=SCOPE_CHOICES, required=True)
    add_parser.add_argument("--tier", choices=TIER_CHOICES, default="semantic")
    add_parser.add_argument("--repo", help="Repository path for repo-scoped memories.")
    add_parser.add_argument("--kind", choices=KIND_CHOICES, required=True)
    add_parser.add_argument("--summary", required=True, help="Short durable memory summary.")
    add_parser.add_argument("--details", default="", help="Longer explanation.")
    add_parser.add_argument("--tags", nargs="*", default=[], help="Optional tags.")
    add_parser.add_argument("--source", default="user-confirmed", help="Origin of the memory.")
    add_parser.add_argument("--confidence", choices=CONFIDENCE_CHOICES, default="confirmed")
    add_parser.add_argument("--status", choices=STATUS_CHOICES, default="active")
    add_parser.set_defaults(func=cmd_add)

    save_parser = subparsers.add_parser("save", help="Alias for add.")
    for action in add_parser._actions:
        if action.dest in {"help", "command"}:
            continue
        save_parser._add_action(action)
    save_parser.set_defaults(func=cmd_add)

    search_parser = subparsers.add_parser("search", help="Search saved memories.")
    search_parser.add_argument("--query", required=True)
    search_parser.add_argument("--repo", help="Repository path to prioritize.")
    search_parser.add_argument("--limit", type=int, default=8)
    search_parser.set_defaults(func=cmd_search)

    recall_parser = subparsers.add_parser(
        "recall",
        help="Recall likely-applicable memories for the current task.",
    )
    recall_parser.add_argument("--task", required=True, help="Current user request or task summary.")
    recall_parser.add_argument("--repo", help="Repository path to prioritize.")
    recall_parser.add_argument("--limit", type=int, default=5)
    recall_parser.set_defaults(func=cmd_recall)

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="Backwards-compatible alias for recall.",
    )
    preflight_parser.add_argument("--task", required=True, help="Current user request or task summary.")
    preflight_parser.add_argument("--repo", help="Repository path to prioritize.")
    preflight_parser.add_argument("--limit", type=int, default=5)
    preflight_parser.set_defaults(func=cmd_recall)

    suggest_parser = subparsers.add_parser(
        "suggest",
        help="Evaluate whether a candidate should become a memory.",
    )
    suggest_parser.add_argument("--repo", help="Repository path for repo-scoped suggestions.")
    suggest_parser.add_argument("--summary", required=True)
    suggest_parser.add_argument("--details", default="")
    suggest_parser.add_argument("--kind", choices=KIND_CHOICES)
    suggest_parser.add_argument("--scope", choices=SUGGEST_SCOPE_CHOICES, default="auto")
    suggest_parser.add_argument("--tags", nargs="*", default=[], help="Optional tags.")
    suggest_parser.set_defaults(func=cmd_suggest)

    promote_parser = subparsers.add_parser("promote-core", help="Move a memory into core.")
    promote_parser.add_argument("--id", required=True, help="Memory id.")
    promote_parser.set_defaults(func=cmd_promote_core)

    demote_parser = subparsers.add_parser("demote-core", help="Move a core memory back to semantic.")
    demote_parser.add_argument("--id", required=True, help="Memory id.")
    demote_parser.set_defaults(func=cmd_demote_core)

    list_parser = subparsers.add_parser("list", help="List saved memories.")
    list_parser.add_argument("--repo", help="Repository path to list.")
    list_parser.add_argument("--scope", choices=("all", "global", "repo"), default="all")
    list_parser.add_argument("--tier", choices=("all",) + TIER_CHOICES, default="all")
    list_parser.add_argument("--include-archived", action="store_true")
    list_parser.set_defaults(func=cmd_list)

    export_parser = subparsers.add_parser(
        "export-agents",
        help="Render repo memories as an AGENTS.md snippet.",
    )
    export_parser.add_argument("--repo", required=True, help="Repository path.")
    export_parser.set_defaults(func=cmd_export_agents)

    sync_context_parser = subparsers.add_parser(
        "sync-context",
        help="Project memories into a git-friendly context repository.",
    )
    sync_context_parser.add_argument("--repo", help="Repository path for repo-scoped projection.")
    sync_context_parser.set_defaults(func=cmd_sync_context)

    init_context_parser = subparsers.add_parser(
        "init-context",
        help="Initialize a context repository projection.",
    )
    init_context_parser.add_argument("--repo", help="Repository path for repo-scoped initialization.")
    init_context_parser.set_defaults(func=cmd_sync_context)

    inspect_context_parser = subparsers.add_parser(
        "inspect-context",
        help="Inspect a projected context repository.",
    )
    inspect_context_parser.add_argument("--repo", help="Repository path for repo-scoped inspection.")
    inspect_context_parser.set_defaults(func=cmd_inspect_context)

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Audit projected context repository health and sizing.",
    )
    doctor_parser.add_argument("--repo", help="Repository path for repo-scoped diagnostics.")
    doctor_parser.set_defaults(func=cmd_doctor)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
