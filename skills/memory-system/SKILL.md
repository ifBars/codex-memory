---
name: memory-system
description: Use when repo conventions, user preferences, or durable lessons may matter and should be recalled or saved through the tiered memory store in `~/.codex/memories` or `$CODEX_HOME/memories`.
---

# Codex Memory Skill

This skill gives Codex a practical long-term memory workflow without relying on Windows hooks.

## Goals

- Reuse durable user and repo context across future conversations.
- Recall memory cheaply on most repo-aware or preference-sensitive turns.
- Ask to remember things consistently, but not excessively.
- Keep the source of truth local and inspectable.
- Keep a git-friendly context repository projection available for progressive disclosure.
- Promote stable repo rules into `AGENTS.md` only with explicit user approval.

## Memory root

Use:

- `~/.codex/memories`
- `$CODEX_HOME/memories` when `CODEX_HOME` is set

Do not create a second memory store somewhere else unless the user explicitly asks for it.

## Helper script

Use this script for memory operations:

- `python <plugin-root>/scripts/memory_store.py ...`

Treat `<plugin-root>` as the installed `codex-memory` plugin directory.

- Repo marketplace install: `.`
- Personal install: `~/.codex/plugins/codex-memory`

## Retrieval workflow

1. Before most repo-aware or preference-sensitive work, run a recall.
2. If a repo path is known, include it so repo memory outranks global memory.
3. Apply core memories automatically when relevant.
4. Apply additional retrieved memories only if they are relevant and non-conflicting.
5. Treat `AGENTS.md` as stronger than plugin memory when they conflict.

Default retrieval command:

```powershell
python <plugin-root>/scripts/memory_store.py recall --repo "<repo-path>" --task "<current user request>"
```

Compatibility alias:

```powershell
python <plugin-root>/scripts/memory_store.py preflight --repo "<repo-path>" --task "<current user request>"
```

Context repository helpers:

```powershell
python <plugin-root>/scripts/memory_store.py init-context --repo "<repo-path>"
python <plugin-root>/scripts/memory_store.py sync-context --repo "<repo-path>"
python <plugin-root>/scripts/memory_store.py inspect-context --repo "<repo-path>"
python <plugin-root>/scripts/memory_store.py doctor --repo "<repo-path>"
```

## Memory tiers

- `core`
  - tiny, curated, always-loaded, stable
- `semantic`
  - preferences, conventions, workflows, facts, procedures
- `episodic`
  - sparse incidents, debugging lessons, successes/failures

Prefer semantic by default. Use episodic only for prior incidents that should be recalled on strong similarity.

## Write workflow

1. Near the end of a turn, consider whether exactly one durable memory candidate emerged.
2. Run `suggest` for that candidate.
3. If `suggest` rejects it with `reason == "not_reusable_enough"` and returns a `rewrite_candidate`, rewrite once using that candidate and rerun `suggest`.
4. If the rewritten `suggest` still rejects it, do not ask.
5. If `suggest` accepts it, ask once whether it should be remembered.
6. Save only after the user confirms.
7. If a repo-specific memory becomes a stable standing rule, offer to promote it into `core` and then into `AGENTS.md`.

## Consent rule

- Ask at most once per turn unless the user is explicitly teaching preferences.
- In this runtime, use a standalone final line as the canonical prompt:
  - `Memory Suggestion: Remember "<summary>" for <scope>?`
- Never bury the memory question inside a long paragraph.

## When to ask to remember something

Good candidates:

- persistent user preferences
- recurring formatting or communication preferences
- repo-specific build, test, or tooling rules
- environment quirks that repeatedly affect execution
- corrections the user has made more than once
- durable architectural conventions

Bad candidates:

- one-off task goals
- temporary debug state
- current branch names
- transient file paths that only matter for one turn
- secrets, tokens, or credentials
- anything already enforced by system instructions or existing `AGENTS.md`

## Commands

Recall likely-applicable memories:

```powershell
python <plugin-root>/scripts/memory_store.py recall --repo "<repo-path>" --task "fix the failing build and update the tests"
```

Search manually:

```powershell
python <plugin-root>/scripts/memory_store.py search --repo "<repo-path>" --query "build tool test command"
```

Evaluate a new memory candidate:

```powershell
python <plugin-root>/scripts/memory_store.py suggest --repo "<repo-path>" --summary "Use bun for package management" --details "Do not use npm or pnpm in this repo."
```

If `suggest` returns `rewrite_candidate`, rerun `suggest` once with that rewritten summary/details before deciding whether to ask.

Save a confirmed memory:

```powershell
python <plugin-root>/scripts/memory_store.py add --scope repo --tier semantic --repo "<repo-path>" --kind convention --summary "Use bun for package management" --details "Do not use npm or pnpm in this repo." --source "user-confirmed"
```

Promote a stable repo rule into core:

```powershell
python <plugin-root>/scripts/memory_store.py promote-core --id "<memory-id>"
```

Export repo memories as an `AGENTS.md` snippet:

```powershell
python <plugin-root>/scripts/memory_store.py export-agents --repo "<repo-path>"
```

## Scope rules

- Prefer repo scope when the memory only applies to one codebase or workspace.
- Prefer global scope when it is clearly a user-wide preference.
- If uncertain, ask whether it should be global or repo-specific.

## Safety

- Never store secrets.
- Never silently overwrite repo instructions.
- Treat `AGENTS.md` as a stronger source than plugin memory when they conflict.
