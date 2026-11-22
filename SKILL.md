---
name: ai-dev-wrapped
description: >-
  Generate a minimalist, shareable AI Developer Year-End Wrapped report by scanning
  all local coding agent and harness logs (Claude Code/Desktop, Codex, Antigravity,
  Kimi, OpenClaw, Cursor) and launching an interactive localhost web experience with
  a 6-axis radar chart, archetype classification, witty developer memes, ambient music,
  and one-click PNG export. Activate immediately when the user says "开始吧",
  "给我年终总结", "年终总结", "wrapped", "year in review", or asks to analyze
  their local AI coding habits.
---

# AI Developer Wrapped

Turn a user's multi-harness AI agent logs into a clean, Linear/Apple-Notes-inspired localhost Wrapped report in three deterministic steps.

> **Never read raw multi-GB session transcripts directly.** Always use `scripts/collect.py` to produce a compact, privacy-sanitized summary first.

## Workflow (3 Steps)

### 1. Collect Sanitized Multi-Harness Facts

Resolve `SKILL_DIR` (the directory containing this `SKILL.md`) and run the zero-dependency collector (reads `~/.claude`, `~/.codex`, `~/.gemini/antigravity`, `~/.kimi`, `~/.openclaw`, `~/.cursor` read-only and scrubs IPs, tokens, key paths, and home directories):

```bash
python3 "$SKILL_DIR/scripts/collect.py" --output /tmp/ai_wrapped_facts.json
```

*(Pass `--all-time` if the user asks for lifetime stats across years, or `--tz-offset <hours>` to override host timezone.)*

### 2. Author Personalized Bilingual Archetype & Memes

Read `/tmp/ai_wrapped_facts.json` and review [schemas/persona.schema.json](./schemas/persona.schema.json).

Using **only verified numbers** from `facts.json` (never fabricate counts), write `/tmp/ai_wrapped_persona.json` with:
- `archetype_id`: one of `nightshift-orchestrator`, `swarm-commander`, `shell-alchemist`, `fullstack-maverick`, `verification-purist`, `full-auto-speedrunner`, `minimalist-craftsman`
- `archetype_title` & `archetype_en`: punchy Chinese & English titles
- `one_liner` & `one_liner_en`: one sharp, human sentence capturing their real style
- `secondary_badges` & `secondary_badges_en`: 2–3 crisp tags (e.g. `深夜突击型` / `Night-Shift Raider`, `赛博松鼠党` / `Skill Hoarder`)
- `memes`: 3–4 funny, hyper-accurate cards (`tag`, `tag_en`, `line`, `line_en`) referencing real numbers (e.g. `Grep=1` vs `Bash=160k`, `rtk proxy`, peak `02:00` hour, unused installed skills, max parallel turn)
- `axis_notes` & `axis_notes_en`: short 1-line explanations for all 6 keys (`orchestration`, `shell_craft`, `domain_span`, `verification`, `night_ops`, `autonomy`)

*(Note: If skipped or invalid, `render.py` automatically falls back to `facts.fallback_persona`.)*

### 3. Render, Serve on Localhost & Open Browser

```bash
python3 "$SKILL_DIR/scripts/render.py" \
  --facts /tmp/ai_wrapped_facts.json \
  --persona /tmp/ai_wrapped_persona.json \
  --serve --daemon --open
```

Verify the printed `http://127.0.0.1:<port>/` URL and share a brief summary of their archetype and top stats in chat.
