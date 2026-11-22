---
name: ai-dev-wrapped
description: >-
  Generate a minimalist, viral, shareable AI Developer Year-End Wrapped report by
  auto-discovering and scanning all local AI coding agents, CLIs, and IDEs (Claude
  Code/Desktop, Codex, GitHub Copilot CLI & VS Code Chat, Antigravity, Gemini CLI,
  Cursor, Windsurf, Cline, Roo Code, Kilo Code, OpenCode, Kimi, OpenClaw/AutoClaw,
  Goose, Continue, Aider, Trae, Qoder, Kiro, Qwen Code, Amp, Zed AI, and more)
  and letting the user's own AI agent analyze their bespoke personality,
  Douyin/TikTok-style memes, and universal 6-axis persona radar before launching an
  interactive localhost web page with ambient music and 2x PNG share card export.
  Activate immediately when the user says "开始吧", "给我年终总结", "年终总结",
  "wrapped", "year in review", or asks to analyze their local AI coding habits.
---

# AI Developer Wrapped

Turn a user's local multi-harness AI history into a minimalist, screenshot-ready localhost Year-End Wrapped (Linear Dark & Apple Notes Paper themes).

> **Never read raw multi-GB session transcripts directly.** Run `scripts/collect.py` first to produce a compact, privacy-sanitized summary (`/tmp/ai_wrapped_facts.json`), then **you** (this user's own agent) diagnose their unique personality and write all copy.

---

## Workflow (3 Steps)

### 1. Collect Sanitized Multi-Harness Facts

Resolve `SKILL_DIR` (the directory containing this `SKILL.md`) and run the zero-dependency collector (automatically discovers 35+ local agents across macOS/Linux/Windows `~/.claude`, `~/.codex`, `~/.copilot`, `~/.gemini`, `~/.cursor`, `~/.codeium/windsurf`, `~/.kimi`, `~/.openclaw*`, `~/.local/share/opencode`, `~/.local/share/goose`, `~/.continue`, `~/.aider*`, VS Code/IDE global & workspace storage, plus `~/.qwen`, `~/.trae*`, `~/.qoder*`, `~/.kiro`, `~/.factory`, `~/.openhands`, `~/.vibe`, `~/.amp`, Zed AI — all read-only with IPs, tokens, private keys, emails, and home paths scrubbed):

```bash
python3 "$SKILL_DIR/scripts/collect.py" --output /tmp/ai_wrapped_facts.json
```

*(Pass `--all-time` if the user asks for lifetime stats across years, or `--tz-offset <hours>` to override the host timezone.)*

---

### 2. Analyze Personality Yourself & Write Viral Bilingual Copy (`/tmp/ai_wrapped_persona.json`)

Read `/tmp/ai_wrapped_facts.json` carefully and follow [schemas/persona.schema.json](./schemas/persona.schema.json).

You are acting as BOTH:
1. **Their Brutally Honest AI Sidekick (人格独立分析官)**: Do **NOT** pick from any canned personality menu or generic 7-type template! Inspect this specific user's telemetry ratios in `/tmp/ai_wrapped_facts.json` (plus your honest first-hand impression of how they collaborate with you in this workspace/session) and **invent a 1-of-1 bespoke archetype** that fits *only* them.
2. **A Viral Tech Creator (网感爆款自媒体文案)** writing in Douyin / Xiaohongshu / TikTok / Dev-Twitter cadence — roasting them with love, receipts, and high-contrast hooks. Never sound like an HR review or B2B architecture doc.

#### How to Diagnose Their 1-of-1 Archetype from `/tmp/ai_wrapped_facts.json`
Look for the **weirdest contradiction or signature obsession** across these signals rather than naming a generic trait:
- **Search / Tool Paradox**: Compare native `inventory.grep_calls` / `inventory.glob_calls` against raw `bash_dna.top_commands` (like `grep`, `sed`, `head`, `python3`) and `totals.bash_share_pct`.
- **Delegation vs Micromanagement**: Compare `totals.subagent_sessions / totals.sessions`, `totals.max_parallel_turn`, and `inventory.auto_or_bypass` against `bash_dna.test_cmd_count`, `verification_signals`, and `bash_dna.rtk_proxy_count`.
- **Clock & Addiction Shape**: Inspect the 24-hour shape in `hours[0..23]`, `peak_hour`, `night_owl_pct`, `totals.active_days`, `top_models`, and `harnesses` split (one ride-or-die harness or cheating across 5+ tools?).
- **Gear Hoarding vs Usage**: Compare `inventory.skills_installed` + `inventory.agents_installed` + `inventory.plugins_total` vs `inventory.plugins_unused`.

#### Universal 6-Axis Radar — DO NOT MODIFY
`facts.radar_axes` uses **6 fixed, universal dimensions** across every developer worldwide so share cards stay 100% comparable:
1. `night_owl` (`夜猫纯度` / `Night Owl`) — late-night concentration (22:00–05:00) & peak hour
2. `boss_energy` (`甩手掌柜` / `Boss Energy`) — subagent delegation & multi-tool parallelism
3. `gear_hoarder` (`装备狂魔` / `Gear Hoarder`) — skills, plugins, MCPs, and agent toys collected
4. `trust_issues` (`疑心洁癖` / `Trust Issues`) — verifying, testing, raw checks, diffs
5. `chaos_grit` (`硬核折腾` / `Chaos Grit`) — raw shell grit, piping, heredocs, workspace hopping
6. `ai_addict` (`含AI量` / `AI Addict`) — active days, multi-harness addiction, total AI actions

**Never invent custom axes, rename axis labels, or alter scores.** Write short, funny 1-line `axis_notes` / `axis_notes_en` commenting on the fixed scores above.

#### Viral Copywriting System Rules
1. **Receipts Only (Zero Fake Numbers)**: Every single number, hour, model, tool, or command MUST come verbatim from `/tmp/ai_wrapped_facts.json`. Never fabricate counts.
2. **No Canned Archetypes, No Engineer Jargon**: Never output generic labels (*"Nightshift Orchestrator"*, *"Full-Stack Maverick"*) or stiff prose (*"编排杠杆"*, *"全链路验证闭环"*, *"Workflow orchestration throughput"*). Mint fresh internet slang & everyday life metaphors (`赛博包工头`, `电子包浆`, `精神早高峰`, `松鼠军火库`, `端水大师`, `Main-Character Energy`, `Zero-Trust Control Freak`).
3. **High-Contrast Hook First**: Pit a huge metric against a tiny metric (`Grep=66` vs `bash grep=94,795`), or expose circadian crimes (`03:00 AM` morning commute).
4. **Native Bilingual Adaptation (NOT Literal Translation)**: Write `*_title` / `one_liner` / `memes` in sharp Chinese social-media rhythm AND `*_en` independently in TikTok/X rhythm — same verified receipt, localized punchline.
5. **Minimalist Brevity (Linear / Apple Notes Rule)**: Zero filler slogans. Respect character limits below so cards stay razor clean.

#### Output Schema (`/tmp/ai_wrapped_persona.json`)
- `archetype_id`: Free-form 1-of-1 kebab-case slug you coin for this user (`<= 48` chars).
- `archetype_title` (`2–14` Chinese chars) & `archetype_en` (`2–5` words): Screenshot-worthy 1-of-1 identity coined strictly from their data (never picked from a preset list).
- `one_liner` (`<= 46` Chinese chars) & `one_liner_en` (`<= 140` chars): One killer verdict summing up their entire AI year with 2–3 signature receipts.
- `secondary_badges` (`2–3` tags, `<= 10` Chinese chars each) & `secondary_badges_en` (`<= 24` chars each): Ultra-short tags naming their quirks.
- `memes`: Write **4 distinct roast/flex cards** (`tag`, `tag_en`, `line`, `line_en`):
  - **Card 1 — Contrast Roast (反差打脸)**: Pit two surprising metrics against each other using real numbers from `facts.json`.
  - **Card 2 — Sleep Schedule Expose (作息实锤)**: Roast their `peak_hour` + `night_owl_pct` like exposing their screen-time report.
  - **Card 3 — Hoarder / Obsession Callout (囤积或洁癖)**: Cite `inventory.skills_installed`, `inventory.plugins_total`, `inventory.plugins_unused`, `bash_dna.test_cmd_count`, or `bash_dna.rtk_proxy_count`.
  - **Card 4 — Wild Pop-Culture Metaphor (神级类比)**: Compare how they boss around AI using `totals.max_parallel_turn`, `totals.subagent_sessions`, `harnesses`, or `top_models`.
- `axis_notes` & `axis_notes_en`: 1 crisp roast (`<= 26` Chinese chars / `<= 55` English chars) for all 6 fixed keys: `night_owl`, `boss_energy`, `gear_hoarder`, `trust_issues`, `chaos_grit`, `ai_addict`.

*(Note: `render.py` falls back to a neutral factual snapshot if `--persona` is omitted, so never skip Step 2 during a user conversation.)*

---

### 3. Render, Serve on Localhost & Open Browser

```bash
python3 "$SKILL_DIR/scripts/render.py" \
  --facts /tmp/ai_wrapped_facts.json \
  --persona /tmp/ai_wrapped_persona.json \
  --serve --daemon --open
```

Verify the printed `http://127.0.0.1:<port>/` URL opens cleanly and share a witty 3-line summary of the bespoke archetype you diagnosed for them in chat.
