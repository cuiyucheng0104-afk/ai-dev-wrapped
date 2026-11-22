---
name: ai-dev-wrapped
description: >-
  Generate a minimalist, viral, shareable AI Developer Year-End Wrapped report by
  auto-discovering and scanning 35+ local AI coding agents, CLIs, and IDEs, then
  letting the user's own AI agent analyze their bespoke 1-of-1 persona, compact
  Douyin/TikTok-style memes, Tier Verdict (90% roast + 10% warm encouragement),
  and global calibrated 6-axis radar (0.8x baseline = 70; >100 pierces out of the
  box) before launching an interactive localhost web page with ambient music and
  2x PNG share card export. Activate immediately when the user says "开始吧",
  "给我年终总结", "年终总结", "wrapped", "year in review", or asks to analyze
  their local AI coding habits.
---

# AI Developer Wrapped

Turn a user's local multi-harness AI history into a minimalist, screenshot-ready localhost Year-End Wrapped (Linear Dark & Apple Notes Paper themes).

> **Never read raw multi-GB session transcripts directly.** Run `scripts/collect.py` first to generate a compact, privacy-sanitized summary (`/tmp/ai_wrapped_facts.json`), then **you** (the user's own agent) diagnose their 1-of-1 persona and concise closing verdict.

---

## Workflow (3 Steps)

### 1. Collect Sanitized Multi-Harness Facts

Resolve `SKILL_DIR` (the directory containing this `SKILL.md`) and run the zero-dependency collector (automatically scans 35+ AI CLIs, IDEs, and extensions read-only across macOS/Linux/Windows and scrubs IPs, tokens, private keys, emails, and home paths):

```bash
python3 "$SKILL_DIR/scripts/collect.py" --output /tmp/ai_wrapped_facts.json
```

*(Pass `--all-time` if the user asks for lifetime stats, or `--tz-offset <hours>` to override timezone.)*

---

### 2. Analyze Personality Yourself & Write Punchy Copy (`/tmp/ai_wrapped_persona.json`)

Read `/tmp/ai_wrapped_facts.json` and follow [schemas/persona.schema.json](./schemas/persona.schema.json).

You are acting as BOTH:
1. **1-of-1 Persona Profiler (人格独立诊断官)**: Do **NOT** pick from any canned personality menu! Inspect this user's real telemetry contradictions in `/tmp/ai_wrapped_facts.json` (plus your genuine feel for how they work with you) and **coin an original 1-of-1 archetype**.
2. **Short-Form Viral Creator (短平快爆款自媒体文案)** in Douyin / Xiaohongshu / TikTok / Dev-Twitter rhythm: tight, funny, screenshot-ready, zero long paragraphs.

#### Global Calibrated 6-Axis Scale — DO NOT MODIFY
`facts.radar_axes` uses **6 fixed, universal dimensions** anchored globally (`70` pts = heavy baseline, `88` = elite Tier-1 power user, **`> 100` physically breaks outside the hexagon frame!**):
1. `night_owl` (`夜猫纯度` / `Night Owl`)
2. `boss_energy` (`甩手掌柜` / `Boss Energy`)
3. `gear_hoarder` (`装备狂魔` / `Gear Hoarder`)
4. `trust_issues` (`疑心洁癖` / `Trust Issues`)
5. `chaos_grit` (`硬核折腾` / `Chaos Grit`)
6. `ai_addict` (`含AI量` / `AI Addict`)

**Never rename axes or alter scores.** If any score is **`> 100`**, call out that "off-the-chart / 破表出框" flex in its roast!

#### Copywriting Rules (Concise, Viral, Zero Fluff)
1. **Keep It Short (`字数宁短勿长`)**: Cut every unnecessary word. Every card should read in 2 seconds.
2. **Receipts Only**: Every number, hour, model, or tool cited MUST match `/tmp/ai_wrapped_facts.json` verbatim.
3. **No Engineer Jargon / No Canned Labels**: Ban *"编排杠杆"*, *"闭环"*, *"吞吐"* and canned archetypes. Use vivid internet slang (`包工头`, `赛博松鼠`, `端水大师`, `精神早高峰`, `Main-Character Energy`).
4. **Native Bilingual Adaptation**: Author Chinese & English punchlines independently using the same verified numbers.
5. **Verdict Tone = 90% Crisp Roast + 10% Genuine Encouragement**: Diagnose their real tier/level honestly (superpower + biggest habit quirk/blindspot) and finish with **10% warm, hype encouragement**.

#### Required Output (`/tmp/ai_wrapped_persona.json`)
- `archetype_id`: Free-form 1-of-1 kebab-case slug (`<= 48` chars).
- `archetype_title` (`2–12` Chinese chars) & `archetype_en` (`2–4` words): Screenshot-worthy original label.
- `one_liner` (`<= 38` Chinese chars) & `one_liner_en` (`<= 120` chars): 1 sharp sentence with 2–3 numbers.
- `secondary_badges` (`2–3` tags, `<= 9` Chinese chars each) & `secondary_badges_en` (`<= 22` chars each).
- `memes`: **4 distinct cards** (`tag`, `tag_en`, `line <= 44 Chinese chars`, `line_en <= 135 chars`):
  1. **Contrast Roast**: Pair a huge stat vs a tiny stat (`Grep` tool vs bash `grep`).
  2. **Sleep Crime**: Expose `peak_hour` + `night_owl_pct`.
  3. **Hoarder / Obsession**: Cite `inventory.skills_installed`, `plugins_unused`, `test_cmd_count`, or `rtk_proxy_count`.
  4. **Pop-Culture Metaphor**: Compare how they boss AI around (`max_parallel_turn`, `subagent_sessions`, `harnesses`).
- `axis_notes` & `axis_notes_en`: 1 crisp zinger (`<= 22` Chinese chars / `<= 48` English chars) for all 6 keys (`night_owl`, `boss_energy`, `gear_hoarder`, `trust_issues`, `chaos_grit`, `ai_addict`).
- `verdict_level` (`<= 16` Chinese chars) & `verdict_level_en` (`<= 36` chars): Objective tier badge (e.g. `先锋包工头 · 超前单框流` / `Top-1% Swarm Pioneer`).
- `verdict_body` (`<= 75` Chinese chars) & `verdict_body_en` (`<= 160` chars): Ultra-compact honest tier diagnosis + flaw callout + **10% encouraging closer** (e.g. cut idle plugins, move 3AM runs earlier — your ceiling is scary high, keep shipping!).

---

### 3. Render, Serve on Localhost & Open Browser

```bash
python3 "$SKILL_DIR/scripts/render.py" \
  --facts /tmp/ai_wrapped_facts.json \
  --persona /tmp/ai_wrapped_persona.json \
  --serve --daemon --open
```

Verify `http://127.0.0.1:<port>/` opens cleanly and share a brief 3-line summary in chat.
