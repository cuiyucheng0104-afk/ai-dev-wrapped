# ai-dev-wrapped

**Your AI coding year in review — across every agent harness on your machine.**

[English](./README.md) · [简体中文](./README_CN.md)

`ai-dev-wrapped` is a zero-dependency cross-agent skill that scans local transcripts from **Claude Code / Claude Desktop**, **OpenAI Codex**, **Antigravity**, **Kimi CLI**, **OpenClaw**, and **Cursor**, reverse-engineers how you collaborate with AI, and opens a minimalist Linear / Apple-Notes-inspired localhost experience complete with:

- **Developer Archetype Classification** (`Nightshift Swarm Architect`, `Swarm Commander`, `Shell Alchemist`, `Full-Stack Maverick`, `Verification Purist`, `Full-Auto Speedrunner`, `Minimalist Craftsman`)
- **6-Axis Capability Radar** (`Orchestration`, `Shell Craft`, `Domain Span`, `Verification`, `Night Ops`, `Autonomy`)
- **24h Coding Rhythm & Shell DNA** (heredoc-aware Bash parser, `&&` / pipe rates, top executables, parallel turn depth)
- **Data-Backed Developer Memes** generated from your real stats (zero generic horoscope fluff)
- **Dual Minimalist Themes + Bilingual Toggle (`EN / 中文`)** — Linear Dark & Apple Notes Paper
- **Zero-Dependency Ambient Synth** (Web Audio API pentatonic piano/pad)
- **One-Click 2× Retina Share Card PNG Export**
- **100% Local & Sanitized** — strips IPv4s, `.pem`/SSH key paths, API tokens, emails, and local home paths before rendering

---

## Quick Start

### 1. Install as a Skill

Clone into your preferred agent's skills directory (or symlink to multiple):

```bash
git clone https://github.com/cuiyucheng0104-afk/ai-dev-wrapped.git ~/.claude/skills/ai-dev-wrapped

# Optional: share the same skill with Codex & Antigravity
mkdir -p ~/.codex/skills ~/.gemini/antigravity/skills
ln -s ~/.claude/skills/ai-dev-wrapped ~/.codex/skills/ai-dev-wrapped
ln -s ~/.claude/skills/ai-dev-wrapped ~/.gemini/antigravity/skills/ai-dev-wrapped
```

### 2. Trigger in Chat

Simply tell your agent:

- `"给我年终总结"` / `"开始吧"`
- `"Generate my AI developer wrapped"`

The agent scans your logs into `/tmp/ai_wrapped_facts.json`, authors your bilingual persona & memes, launches a background `127.0.0.1` server, and opens the page in your browser.

### 3. Standalone CLI Usage (Without an Agent)

```bash
python3 scripts/collect.py --output /tmp/ai_wrapped_facts.json
python3 scripts/render.py --facts /tmp/ai_wrapped_facts.json --serve --open
```

---

## Supported Harnesses

| Harness | Local Data Sources Scanned (Read-Only) |
| :--- | :--- |
| **Claude Code / Desktop** | `~/.claude/projects/**/*.jsonl`, `~/.claude/history.jsonl`, `~/.claude.json`, `~/.claude/settings*.json` |
| **OpenAI Codex** | `~/.codex/state_5.sqlite` (`?immutable=1`), `~/.codex/thread_history_1.sqlite`, fallback `sessions/` & `archived_sessions/` |
| **Antigravity** | `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl` |
| **Kimi CLI** | `~/.kimi/sessions/*/*/wire.jsonl` & `context.jsonl` |
| **OpenClaw** | `~/.openclaw/agents/*/sessions/*.jsonl` |
| **Cursor** | `~/.cursor/ai-tracking/ai-code-tracking.db`, `~/.cursor/projects/*/agent-transcripts/` |

---

## Design Philosophy

1. **Zero Build / Zero CDN**: Pure Python 3 standard library + single-file HTML/SVG/Canvas/WebAudio. Works completely offline.
2. **4-Dimension Subtraction**: Inspired by Linear and Apple Notes — no marketing fluff, no redundant helper tooltips, layout-first hierarchy.
3. **Privacy by Default**: Raw prompts, IP addresses, private keys, and tokens never enter `facts.json` or the rendered page.

---

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## License

[MIT](./LICENSE)
