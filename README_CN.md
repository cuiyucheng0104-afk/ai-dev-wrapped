# ai-dev-wrapped

**AI 开发者的跨平台年终总结 Skill —— 扫描你本机所有 Agent / Harness 记录，反推你的真实协作习惯。**

[English](./README.md) · [简体中文](./README_CN.md)

`ai-dev-wrapped` 是一个**零外部依赖**的通用 Skill：自动只读扫描 **Claude Code / Claude Desktop**、**OpenAI Codex**、**Antigravity**、**Kimi CLI**、**OpenClaw**、**Cursor** 等本地历史记录，在几秒内反推出你的 AI 工程人格，并自动打开极简风格的 `localhost` 年终总结网页：

- **开发者人格分类**：深夜蜂群总工 / 蜂群指挥官 / 终端炼金术士 / 跨界特种兵 / 洁癖守门人 / 全自动狂飙派 / 克制极简派
- **六维能力雷达图**：编排杠杆、终端功底、跨界广度、工程洁癖、夜战耐力、放权程度
- **24 小时节律 & Bash 基因**：剥离 heredoc 干扰的真实命令统计、`&&`/管道率、单轮并发峰值
- **基于真实数字的吐槽梗**：用你自己的数据反讽（如 *“Grep=1, Bash=16万”*、*“装了238个技能一半吃灰”*、*“凌晨2点早高峰”*）
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

## 支持的 Agent / Harness

| Harness | 只读采集数据源 |
| :--- | :--- |
| **Claude Code / Desktop** | `~/.claude/projects/**/*.jsonl`、`~/.claude/history.jsonl`、`~/.claude.json`、`~/.claude/settings*.json` |
| **OpenAI Codex** | `~/.codex/state_5.sqlite`（`?immutable=1` 只读快照）、`~/.codex/thread_history_1.sqlite`、以及 JSONL 回退 |
| **Antigravity** | `~/.gemini/antigravity/brain/*/.system_generated/logs/transcript.jsonl` |
| **Kimi CLI** | `~/.kimi/sessions/*/*/wire.jsonl` 与 `context.jsonl` |
| **OpenClaw** | `~/.openclaw/agents/*/sessions/*.jsonl` |
| **Cursor** | `~/.cursor/ai-tracking/ai-code-tracking.db`、`~/.cursor/projects/*/agent-transcripts/` |

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
