# Codex Memory Custom Instructions

Copy-paste this into your Codex custom instructions or system prompt:

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
