# Codex Memory

`codex-memory` is a Codex plugin for durable, consent-driven memory with tiered recall and a git-friendly context repository projection.

This repo is the plugin itself. The repo root is the plugin root.

## Why it is structured this way

OpenAI's current Codex plugin docs say the proper local distribution path is still marketplace-based:

- a plugin bundle with `.codex-plugin/plugin.json`
- a marketplace file in `.agents/plugins/marketplace.json`
- restart Codex after adding or updating the marketplace

They also say self-serve publishing to the official public Plugin Directory is not live yet, so the practical way to share a plugin today is still a Git repo or a local marketplace.

Official docs:

- [Build plugins](https://developers.openai.com/codex/plugins/build?install-scope=workspace)
- [Plugins overview](https://developers.openai.com/codex/plugins)

## What it does

- splits memory into `core`, `semantic`, and `episodic` tiers
- runs lightweight recall for repo-aware or preference-sensitive work
- provides a `suggest` flow for explicit memory consent
- can promote stable repo rules into `core` and export them into `AGENTS.md`
- projects memories into inspectable Markdown context repositories
- exposes a local MCP server named `memory`

By default the memory store lives at `~/.codex/memories`. If `CODEX_HOME` is set, it uses `$CODEX_HOME/memories`.

## Recommended custom instructions

This plugin works best when the agent is already told to use memory selectively instead of treating every turn like a memory event.

Copy-paste version:

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

There is also a standalone copy at [CUSTOM-INSTRUCTIONS.md](C:\Users\ghost\Desktop\Coding\codex-plugins\codex-memory\CUSTOM-INSTRUCTIONS.md).

## Repo install

Use this when someone wants the plugin available inside this checkout.

1. Clone the repo.
2. Install the Python dependencies:

```powershell
python -m pip install -r .\requirements.txt
```

3. Open this repo in Codex.
4. Restart Codex if needed.
5. In the plugin directory, choose the `Codex Memory` marketplace and install `Codex Memory`.

This repo already includes:

- `.codex-plugin/plugin.json`
- `.agents/plugins/marketplace.json`
- `.mcp.json`
- `skills/`
- `scripts/`

The repo marketplace points at the repo root with `source.path: "./"`.

## Personal install

Use this when someone wants `codex-memory` across all workspaces.

1. Copy or clone this repo into `~/.codex/plugins/codex-memory`.
2. Install the Python dependencies:

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

4. Restart Codex.

## Helper commands

Repo install examples:

```powershell
python ./scripts/memory_store.py --help
python ./scripts/memory_store.py recall --repo "<repo-path>" --task "fix the failing build and update tests"
python ./scripts/memory_store.py suggest --repo "<repo-path>" --summary "Use bun for package management" --details "Do not use npm or pnpm in this repo."
python ./scripts/memory_store.py sync-context --repo "<repo-path>"
```

For a personal install, replace `./scripts/...` with `~/.codex/plugins/codex-memory/scripts/...`.

## MCP server

The plugin exposes a local FastMCP server as `memory`.

- config: `.mcp.json`
- entrypoint: `./scripts/memory_mcp_server.py`

Resources include:

- `memory://overview`
- `memory://repositories`
- `memory://global/core`
- `memory://global/semantic`
- `memory://repo/{repo_key}/core`
- `memory://repo/{repo_key}/semantic`
- `memory://repo/{repo_key}/episodic`

Tools include:

- `list_memories`
- `search_memories`
- `recall_memories`
- `suggest_memory`
- `add_memory`
- `inspect_context_repo`
- `sync_context_repo`
- `doctor_memory_store`

## For Agents

Once this repo is on GitHub, people can point another agent at the README and use a prompt like this:

```text
Install the codex-memory Codex plugin from this repo by following the README:
<README_URL>

If I want it only in this checkout, use the Repo install section.
If I want it across all workspaces, use the Personal install section.
After setup, restart Codex and make sure Codex Memory is enabled from the plugin directory.
```

Short version:

```text
Install the Codex Memory plugin from <README_URL> and follow the Personal install section.
```

If you also want the same memory behavior I use, copy the custom instructions from:

```text
<README_URL>
or
<CUSTOM_INSTRUCTIONS_URL>
```

## Development

Run the test suite from the repo root:

```powershell
python -m unittest discover -s tests -v
```
