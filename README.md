# ai-dev-wrapped

**Your AI coding year in review — across every agent assistant & IDE on your machine.**

[English](./README.md) · [简体中文](./README_CN.md)

`ai-dev-wrapped` is a zero-dependency universal skill that auto-discovers and scans **35+ local AI coding agents, CLIs, and IDEs** (Claude Code/Desktop, Codex, GitHub Copilot CLI & VS Code Chat, Antigravity, Gemini CLI, Cursor, Windsurf, Cline, Roo Code, Kilo Code, OpenCode, Kimi CLI, OpenClaw, AutoClaw, Goose, Continue, Aider, Trae, Qoder, Kiro, Qwen Code, OpenHands, Amp, Zed AI, and more).

Then **your own AI agent analyzes your unique habits itself** (using the viral copywriting prompt in [`SKILL.md`](./SKILL.md) — zero hardcoded personality buckets) and opens a minimalist Linear / Apple-Notes-inspired localhost experience complete with:

- **100% Agent-Analyzed Bespoke Persona (Zero Hardcoded Buckets)**: Python never assigns canned templates — `SKILL.md` prompts your own AI agent to analyze your anomalies and coin a 1-of-1 archetype & Douyin/TikTok-style roasts strictly grounded in `facts.json`
- **Universal 6-Axis AI Persona Radar** (standardized across every developer so share cards compare apples-to-apples): `Night Owl`, `Boss Energy`, `Gear Hoarder`, `Trust Issues`, `Chaos Grit`, `AI Addict`
- **24h Body Clock & Shell Habits** (heredoc-aware Bash parser, `&&` / pipe rates, top executables, parallel turn depth)
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

## Supported Harnesses (35+ Auto-Discovered Agents, CLIs & IDEs)

`collect.py` automatically scans read-only local data across macOS, Linux, and Windows (only active agents with real session/tool logs are reported — never empty skill-only directories):

| Category | Supported Tools & Data Sources |
| :--- | :--- |
| **CLI & Terminal Agents** | **Claude Code** (`~/.claude/projects/**/*.jsonl`, `history.jsonl`), **OpenAI Codex** (`~/.codex/state_5.sqlite`, `thread_history_1.sqlite`, JSONL), **GitHub Copilot CLI** (`~/.copilot/session-state/*/events.jsonl`), **Gemini CLI** (`~/.gemini/tmp/*/chats/*.json`, `logs.json`), **Kimi CLI** (`~/.kimi/sessions/`), **OpenCode** (`~/.local/share/opencode/` SQLite & JSON), **Goose** (`~/.local/share/goose/`, `~/.config/goose/`), **Aider** (`~/.aider.chat.history.md`, `~/.aider-desk/`) |
| **AI IDEs & Desktop Apps** | **Claude Desktop**, **Antigravity** (`~/.gemini/antigravity/brain/`), **Cursor** (`~/.cursor/ai-tracking/`, `agent-transcripts/`), **Windsurf / Cascade** (`~/.codeium/windsurf/cascade/`, IDE chatStorage), **Trae / Trae CN** (`~/.trae*`), **Qoder** (`~/.qoder*`), **Kiro** (`~/.kiro`), **Zed AI** (`zed` conversations) |
| **IDE Extensions** | **GitHub Copilot Chat** (VS Code / Insiders / VSCodium `workspaceStorage/*/chatSessions`), **Cline** (`saoudrizwan.claude-dev`, `~/.cline`), **Roo Code** (`rooveterinaryinc.roo-cline`, `~/.roo`), **Kilo Code** (`kilocode.kilo-code`, `~/.kilocode`), **Continue** (`~/.continue/sessions/`) |
| **Multi-Agent / Emerging CLIs** | **OpenClaw** (`~/.openclaw`), **AutoClaw** (`~/.openclaw-autoclaw`), **Amp**, **Crush**, **Qwen Code**, **Factory Droid**, **OpenHands**, **Mistral Vibe**, **Hermes**, **JetBrains Junie**, **Augment**, **iFlow**, **Grok CLI**, **Lingma**, **CodeBuddy**, **Pi**, **Mux**, **Zencoder**, **Rovo Dev**, **CodeArts Doer** |

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
