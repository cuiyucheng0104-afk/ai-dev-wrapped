# ai-dev-wrapped

**AI 开发者的全机跨平台年终总结 Skill —— 自动扫描电脑里几乎所有 AI 编程助手 / Agent 记录，由你自己的 Agent 现场毒舌分析专属人格。**

[English](./README.md) · [简体中文](./README_CN.md)

`ai-dev-wrapped` 是一个**零外部依赖**的通用 Skill：自动只读扫描电脑里的 **35+ 主流 AI 编程助手、CLI 与 IDE 插件**（覆盖 Claude Code / Desktop、Codex、GitHub Copilot CLI & VS Code Chat、Antigravity、Gemini CLI、Cursor、Windsurf、Cline、Roo Code、Kilo Code、OpenCode、Kimi CLI、OpenClaw、AutoClaw、Goose、Continue、Aider、Trae、Qoder、Kiro、Qwen Code、OpenHands、Amp、Zed AI 等），不设预设人格桶——直接用 [`SKILL.md`](./SKILL.md) 的提示词交由**用户自己的 Agent** 分析反推 1-of-1 人格，并自动拉起极简风格 `localhost` 网页：

- **100% 由你自己的 Agent 现场分析人格（零预设模板桶）**：`collect.py` 只负责中性采集与脱敏，不预设“七种固定人格”；`SKILL.md` 内置系统提示词，让用户自己的 AI 结合反差数据与协作习惯，现场发明专属的一人一版高网感人设与抖音 / 小红书 / TikTok 吐槽梗
- **全球统一六维含 AI 人格雷达图**（所有用户同尺度对比，不按个人私改维度）：`夜猫纯度 Night Owl`、`甩手掌柜 Boss Energy`、`装备狂魔 Gear Hoarder`、`疑心洁癖 Trust Issues`、`硬核折腾 Chaos Grit`、`含AI量 AI Addict`
- **24 小时作息图 & 终端手癖榜**（剥离 heredoc 干扰的真实命令统计、`&&`/管道率、单轮并发峰值）
- **Linear 暗夜 / Apple 备忘录纸感双主题 + 中英文秒切**
- **零外链轻音乐配乐**（Web Audio API 本地合成柔和环境音）
- **一键导出 2× 高清分享长图（PNG）**
- **100% 本地处理 & 隐私强脱敏**：默认剔除 IPv4、`.pem`/SSH 密钥路径、API Token、邮箱与本机家目录路径

---

## 快速开始

### 1. 安装 Skill

克隆到任意 Agent 的技能目录（可同时软链给多个 Agent 共用）：

```bash
git clone https://github.com/cuiyucheng0104-afk/ai-dev-wrapped.git ~/.claude/skills/ai-dev-wrapped

# 可选：同步给 Codex 与 Antigravity
mkdir -p ~/.codex/skills ~/.gemini/antigravity/skills
ln -s ~/.claude/skills/ai-dev-wrapped ~/.codex/skills/ai-dev-wrapped
ln -s ~/.claude/skills/ai-dev-wrapped ~/.gemini/antigravity/skills/ai-dev-wrapped
```

### 2. 对话触发

安装后只需在对话里输入：

- `开始吧`
- `给我年终总结`
- `Generate my AI developer wrapped`

Agent 会自动运行采集器、结合你的真实数据写出专属中英双语人格与梗、在 `127.0.0.1` 起服务并自动拉起浏览器打开。

### 3. 纯命令行直出（不经过 AI 对话）

```bash
python3 scripts/collect.py --output /tmp/ai_wrapped_facts.json
python3 scripts/render.py --facts /tmp/ai_wrapped_facts.json --serve --open
```

---

## 支持的 AI 编程助手（全机自动发现 35+ Agent / CLI / IDE）

`collect.py` 跨 macOS / Linux / Windows 自动只读探测常见 AI 工具日志（仅统计存在真实会话/调用的活跃工具，不会把空配置或同步过来的技能目录误算为活跃助手）：

| 类别 | 自动支持的工具与本地数据源 |
| :--- | :--- |
| **终端 CLI Agent** | **Claude Code** (`~/.claude/projects/**/*.jsonl` 等)、**OpenAI Codex** (`~/.codex/state_5.sqlite`、JSONL)、**GitHub Copilot CLI** (`~/.copilot/session-state/*/events.jsonl`)、**Gemini CLI** (`~/.gemini/tmp/*/chats/*.json`)、**Kimi CLI** (`~/.kimi/sessions/`)、**OpenCode** (`~/.local/share/opencode/` SQLite/JSON)、**Goose** (`~/.local/share/goose/` / `.config/goose`)、**Aider** (`~/.aider.chat.history.md` / `.aider-desk`) |
| **AI IDE & 桌面客户端** | **Claude Desktop**、**Antigravity** (`~/.gemini/antigravity/brain/`)、**Cursor** (`~/.cursor/ai-tracking/` 与 `agent-transcripts`)、**Windsurf / Cascade** (`~/.codeium/windsurf/cascade/`)、**Trae / Trae CN** (`~/.trae*`)、**Qoder** (`~/.qoder*`)、**Kiro** (`~/.kiro`)、**Zed AI** |
| **编辑器扩展插件** | **GitHub Copilot Chat** (VS Code / Insiders / VSCodium `workspaceStorage/*/chatSessions`)、**Cline** (`saoudrizwan.claude-dev`)、**Roo Code** (`rooveterinaryinc.roo-cline`)、**Kilo Code** (`kilocode.kilo-code`)、**Continue** (`~/.continue/sessions/`) |
| **自主蜂群与新兴 Agent** | **OpenClaw** (`~/.openclaw`)、**AutoClaw** (`~/.openclaw-autoclaw`)、**Amp**、**Crush**、**Qwen Code**、**Factory Droid**、**OpenHands**、**Mistral Vibe**、**Hermes**、**JetBrains Junie**、**Augment**、**iFlow**、**Grok CLI**、**Lingma**、**CodeBuddy**、**Pi**、**Mux**、**Zencoder**、**Rovo Dev**、**CodeArts Doer** |

---

## 设计原则

1. **零构建 / 零 CDN**：纯 Python 3 标准库 + 单体 HTML/SVG/Canvas/WebAudio，断网也能完整运行。
2. **极简做减法**：对标 Linear 官网与 Apple 备忘录，砍掉冗余标语与说明文字，靠网格与排版直接自解释。
3. **默认脱敏**：绝不把原始 Prompt、IP、密钥、Token 写入中间文件或前端页面，放心导出分享图。

---

## 自测

```bash
python3 -m unittest discover -s tests -v
```

## 开源协议

[MIT](./LICENSE)
