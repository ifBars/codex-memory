# Codex Memory

I created `codex-memory` after getting annoyed with constantly telling my agents, "no, don't do that, do this instead," and then having to keep updating `AGENTS.md` or other instruction files to restate the same rules.

This plugin aims to fix that by giving your agents a memory system that can work both per repo and globally, while also integrating back into `AGENTS.md` when that makes sense.

The end result is an experience where your agents actually learn from mistakes instead of making you reteach the same lessons every few sessions.

## Quick install

If you want this plugin across all workspaces:

1. Clone this repo into `~/.codex/plugins/codex-memory`
2. Install dependencies:

```powershell
python -m pip install -r ~/.codex/plugins/codex-memory/requirements.txt
```

3. Add this to `~/.agents/plugins/marketplace.json`:

```json
{
  "name": "my-plugins",
  "interface": {
    "displayName": "My Plugins"
  },
  "plugins": [
    {
      "name": "codex-memory",
      "source": {
        "source": "local",
        "path": "./.codex/plugins/codex-memory"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

4. Restart or refresh Codex
5. Enable `Codex Memory` from the plugin directory

## For agents

Paste this into Codex:

```text
Install the codex-memory Codex plugin by following this README:
https://github.com/ifBars/codex-memory/blob/main/README.md

If I want it across all workspaces, use the Quick install section.
If I only want it in one checkout, use the Repo-only install section.
After setup, refresh Codex and make sure Codex Memory is enabled.
```

This plugin works best when the agent is already told to use memory selectively.

If you also want the agent to use the skill consistently without asking, put this into your "Custom Instructions" in Codex settings too:

```text
Use memory only when prior context is likely to change execution, not for trivial or cosmetic edits.

Recall memory when:
- the task affects architecture, workflows, tooling, testing, or repo conventions
- the user states a durable preference or recurring correction
- a reusable lesson is likely to matter again

Skip memory for:
- small copy, styling, or isolated UI tweaks
- one-off debugging state
- temporary task details or secrets

Apply recalled memory only when relevant and non-conflicting.

If exactly one durable reusable rule emerges, check whether it should be remembered.
Ask at most once per turn, and only for stable preferences, conventions, workflows, or reusable lessons.
Do not ask to remember incident summaries unless they are rewritten as reusable rules.
```

## What it does

`codex-memory` organizes memory into three tiers:

- `core`: tiny, always-relevant standing rules
- `semantic`: preferences, conventions, workflows, and reusable facts
- `episodic`: sparse lessons from past incidents when they are likely to matter again

It supports:

- selective recall for repo-aware or preference-sensitive work
- explicit `suggest` flow before asking to remember something
- promotion of stable repo rules into `AGENTS.md`
- projection into local Markdown context repositories
- a local MCP server named `memory`

By default memory lives in `~/.codex/memories`. If `CODEX_HOME` is set, it uses `$CODEX_HOME/memories`.

## Repo-only install

If you only want this plugin inside one checkout:

1. Clone this repo
2. Install dependencies from the repo root:

```powershell
python -m pip install -r .\requirements.txt
```

3. Open the repo in Codex
4. Refresh Codex if needed
5. Install `Codex Memory` from the local plugin directory

This works because the repo already includes:

- `.codex-plugin/plugin.json`
- `.agents/plugins/marketplace.json`
- `.mcp.json`
- `skills/`
- `scripts/`

## Useful commands

```powershell
python ./scripts/memory_store.py --help
python ./scripts/memory_store.py recall --repo "<repo-path>" --task "fix the failing build and update tests"
python ./scripts/memory_store.py suggest --repo "<repo-path>" --summary "Use bun for package management" --details "Do not use npm or pnpm in this repo."
python ./scripts/memory_store.py sync-context --repo "<repo-path>"
```

For a personal install, replace `./scripts/...` with `~/.codex/plugins/codex-memory/scripts/...`.

## Notes

Current Codex plugin distribution is still marketplace-based local/repo installation rather than self-serve public directory publishing.

Official docs:

- [Build plugins](https://developers.openai.com/codex/plugins/build?install-scope=workspace)
- [Plugins overview](https://developers.openai.com/codex/plugins)