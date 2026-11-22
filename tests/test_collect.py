import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COLLECT = ROOT / "scripts" / "collect.py"


def make_fixture_home(base: Path) -> Path:
    home = base / "home"
    home.mkdir(parents=True, exist_ok=True)

    # 1. Claude Desktop + CLI + settings + .claude.json
    claude_dir = home / ".claude"
    proj = claude_dir / "projects" / "-Users-dev-secret-repo"
    sub_dir = proj / "s1" / "subagents"
    sub_dir.mkdir(parents=True, exist_ok=True)

    s1_lines = [
        {
            "type": "user",
            "entrypoint": "claude-desktop",
            "permissionMode": "auto",
            "timestamp": "2026-11-20T18:30:00Z",
            "cwd": "/Users/dev/secret-repo",
            "message": {"role": "user", "content": "Deploy to 203.0.113.42 with token sk-ant-secret1234567890abcdef"},
        },
        {
            "type": "assistant",
            "entrypoint": "claude-desktop",
            "requestedModel": "claude-opus-5-5@203.0.113.42",
            "effort": "xhigh",
            "timestamp": "2026-11-20T18:31:00Z",
            "message": {
                "id": "msg_1",
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "t1",
                        "name": "Bash",
                        "input": {
                            "command": (
                                "cd /Users/dev/secret-repo && "
                                "ssh -i ~/.ssh/prod_key.pem root@203.0.113.42 'uptime' && "
                                "rtk proxy git -c core.quotepath=false diff HEAD~1 | head -n 20\n"
                                "python3 - <<'EOF'\n"
                                "import os, json\n"
                                "print('ok')\n"
                                "EOF"
                            ),
                            "description": "check prod",
                        },
                    },
                    {"type": "tool_use", "id": "t2", "name": "Read", "input": {"file_path": "/Users/dev/secret-repo/app.py"}},
                ],
            },
        },
        {
            "type": "assistant",
            "entrypoint": "claude-desktop",
            "requestedModel": "claude-opus-5-5",
            "timestamp": "2026-11-20T18:32:00Z",
            "message": {
                "id": "msg_2",
                "role": "assistant",
                "content": [
                    {"type": "tool_use", "id": "t3", "name": "Workflow", "input": {"script": "console.log(1)"}},
                    {"type": "tool_use", "id": "t4", "name": "mcp__Claude_Browser__computer", "input": {"action": "screenshot"}},
                    {"type": "tool_use", "id": "t5", "name": "ToolSearch", "input": {"query": "select:mcp__ccd_pr__get_status"}},
                ],
            },
        },
    ]
    (proj / "s1.jsonl").write_text("\n".join(json.dumps(x) for x in s1_lines) + "\n", encoding="utf-8")

    # Prior year session (2025) to verify --year filtering vs --all-time
    (proj / "old2025.jsonl").write_text(
        json.dumps({
            "type": "assistant",
            "entrypoint": "claude-desktop",
            "timestamp": "2025-05-01T10:00:00Z",
            "message": {"id": "old1", "role": "assistant", "content": [{"type": "tool_use", "id": "to1", "name": "Read", "input": {}}]},
        }) + "\n",
        encoding="utf-8",
    )

    sub_line = {
        "type": "assistant",
        "entrypoint": "claude-desktop",
        "requestedModel": "claude-sonnet-5-5",
        "timestamp": "2026-11-20T19:00:00Z",
        "message": {
            "id": "msg_sub_1",
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "ts1", "name": "Bash", "input": {"command": "pytest -q && grep -rn foo ."}}],
        },
    }
    (sub_dir / "agent-a1.jsonl").write_text(json.dumps(sub_line) + "\n", encoding="utf-8")

    (claude_dir / "history.jsonl").write_text(
        json.dumps({"display": "hi", "timestamp": 1793000000000, "project": "/Users/dev/cli-proj", "sessionId": "cli1"}) + "\n",
        encoding="utf-8",
    )
    (claude_dir / "settings.json").write_text(
        json.dumps({"permissions": {"defaultMode": "auto"}, "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "rtk hook claude"}]}]}}),
        encoding="utf-8",
    )
    (home / ".claude.json").write_text(
        json.dumps({
            "numStartups": 42,
            "skillUsage": {"loop": {"usageCount": 12}, "superpowers:verification-before-completion": {"usageCount": 5}},
            "pluginUsage": {"p1": {"usageCount": 3}, "p2": {"usageCount": 0}, "p3": {"usageCount": 0}},
        }),
        encoding="utf-8",
    )
    (claude_dir / "skills" / "demo-skill").mkdir(parents=True, exist_ok=True)
    (claude_dir / "skills" / "unused-skill").mkdir(parents=True, exist_ok=True)
    (claude_dir / "agents").mkdir(parents=True, exist_ok=True)
    (claude_dir / "agents" / "reviewer.md").write_text("# rev", encoding="utf-8")

    # 2. Codex WAL SQLite (including subagent row)
    codex_dir = home / ".codex"
    codex_dir.mkdir(parents=True, exist_ok=True)
    con_s = sqlite3.connect(codex_dir / "state_5.sqlite")
    con_s.execute("PRAGMA journal_mode=WAL")
    con_s.execute("CREATE TABLE threads (id TEXT, created_at_ms INTEGER, cwd TEXT, model TEXT, tokens_used INTEGER, approval_mode TEXT, reasoning_effort TEXT, agent_role TEXT)")
    con_s.execute("INSERT INTO threads VALUES ('th1', 1795200000000, '/Users/dev/codex-app', 'gpt-5-codex', 150000, 'never', 'high', NULL)")
    con_s.execute("INSERT INTO threads VALUES ('th2', 1795200001000, '/Users/dev/codex-app', 'gpt-5-codex', 5000, 'never', 'high', 'explorer')")
    con_s.commit()
    con_s.close()

    con_h = sqlite3.connect(codex_dir / "thread_history_1.sqlite")
    con_h.execute("PRAGMA journal_mode=WAL")
    con_h.execute("CREATE TABLE thread_items (thread_id TEXT, item_type TEXT, created_at_ms INTEGER, item_json TEXT)")
    con_h.execute(
        "INSERT INTO thread_items VALUES (?, ?, ?, ?)",
        ("th1", "commandExecution", 1795200001000, json.dumps({"command": "/bin/zsh -lc 'git status && cargo test'"})),
    )
    con_h.execute(
        "INSERT INTO thread_items VALUES (?, ?, ?, ?)",
        ("th1", "mcpToolCall", 1795200002000, json.dumps({"server": "playwright", "tool": "navigate"})),
    )
    con_h.commit()
    con_h.close()

    # 3. Antigravity (real 'args' + JSON-quoted CommandLine + non-standard fractional digits)
    ag_log = home / ".gemini" / "antigravity" / "brain" / "c1" / ".system_generated" / "logs"
    ag_log.mkdir(parents=True, exist_ok=True)
    (ag_log / "transcript.jsonl").write_text(
        json.dumps({"type": "USER_INPUT", "created_at": "2026-11-21T18:00:00.1234Z", "content": "check"}) + "\n"
        + json.dumps({
            "type": "PLANNER_RESPONSE",
            "created_at": "2026-11-21T18:01:00Z",
            "tool_calls": [
                {"name": "read_file", "args": {"Path": "/tmp/a"}},
                {"name": "run_command", "args": {"CommandLine": '"rg -n foo . && jq . a.json"'}},
            ],
        }) + "\n",
        encoding="utf-8",
    )

    # 4. Kimi
    kimi_s = home / ".kimi" / "sessions" / "proj1" / "ks1"
    kimi_s.mkdir(parents=True, exist_ok=True)
    (kimi_s / "wire.jsonl").write_text(
        json.dumps({"timestamp": 1795205000.0, "message": {"type": "TurnBegin", "payload": {"user_input": [{"type": "text", "text": "fix"}]}}}) + "\n",
        encoding="utf-8",
    )
    (kimi_s / "context.jsonl").write_text(
        json.dumps({"role": "assistant", "tool_calls": [{"type": "function", "function": {"name": "Shell", "arguments": "{\"command\": \"ls -la && docker ps\"}"}}]}) + "\n",
        encoding="utf-8",
    )

    # 5. OpenClaw
    oc_s = home / ".openclaw" / "agents" / "main" / "sessions"
    oc_s.mkdir(parents=True, exist_ok=True)
    (oc_s / "oc1.jsonl").write_text(
        json.dumps({"type": "model_change", "provider": "moonshot", "modelId": "kimi-k2.5", "timestamp": "2026-11-19T17:00:00Z"}) + "\n"
        + json.dumps({"type": "message", "timestamp": "2026-11-19T17:01:00Z", "message": {"role": "assistant", "content": [{"type": "toolCall", "name": "exec", "arguments": {"command": "curl -s http://localhost:3000"}}]}}),
        encoding="utf-8",
    )

    # 6. Cursor (agent-transcripts/<uuid>/<uuid>.jsonl + ai-code-tracking.db)
    cur_tr = home / ".cursor" / "projects" / "demo-win" / "agent-transcripts" / "u1"
    cur_tr.mkdir(parents=True, exist_ok=True)
    tr_file = cur_tr / "u1.jsonl"
    tr_file.write_text(
        json.dumps({"role": "assistant", "message": {"content": [{"type": "tool_use", "name": "Shell", "input": {"command": "fd . && fd -t f && wc -l a.py"}}]}}) + "\n",
        encoding="utf-8",
    )
    # Set mtime inside 2026
    os.utime(tr_file, (1795206000, 1795206000))

    cur_db_dir = home / ".cursor" / "ai-tracking"
    cur_db_dir.mkdir(parents=True, exist_ok=True)
    con_c = sqlite3.connect(cur_db_dir / "ai-code-tracking.db")
    con_c.execute("CREATE TABLE ai_code_hashes (hash TEXT, source TEXT, fileExtension TEXT, timestamp INTEGER, model TEXT)")
    con_c.execute("INSERT INTO ai_code_hashes VALUES ('h1', 'composer', '.ts', 1795206000000, 'claude-sonnet')")
    con_c.commit()
    con_c.close()

    return home


class TestCollect(unittest.TestCase):
    def test_collect_multi_harness_and_sanitization(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            home = make_fixture_home(tmp_path)
            out = tmp_path / "facts.json"

            env = os.environ.copy()
            env["HOME"] = str(home)
            env["LC_ALL"] = "C"
            env["TZ"] = "UTC"

            # Run without --tz-offset to verify auto host timezone detection (UTC -> UTC+0)
            proc = subprocess.run(
                [sys.executable, "-I", str(COLLECT), "--home", str(home), "--year", "2026", "--output", str(out)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, f"stderr={proc.stderr}")
            raw = out.read_text(encoding="utf-8")
            data = json.loads(raw)

            self.assertEqual(data["timezone_label"], "UTC+0")
            harnesses = {h["id"]: h for h in data["harnesses"]}
            for hid in ("claude", "codex", "antigravity", "kimi", "openclaw", "cursor"):
                self.assertIn(hid, harnesses, f"missing harness {hid}")
                self.assertTrue(harnesses[hid]["detected"])
                self.assertGreater(harnesses[hid]["sessions"], 0)

            # Verify year filtering excluded 2025 Claude session (1 main 2026 + 1 history = 2)
            self.assertEqual(harnesses["claude"]["sessions"], 2)
            self.assertEqual(harnesses["codex"]["subagents"], 1)

            # Verify Antigravity JSON-quoted args["CommandLine"] & Cursor Shell parsed into Bash DNA
            top_verbs = {item["name"] for item in data["bash_dna"]["top_commands"]}
            self.assertNotIn("import", top_verbs)
            self.assertNotIn("EOF", top_verbs)
            self.assertIn("ssh", top_verbs)
            self.assertIn("rg", top_verbs)
            self.assertIn("jq", top_verbs)
            self.assertIn("fd", top_verbs)

            # Strict privacy sanitization across emitted fields
            self.assertNotIn("203.0.113.42", raw)
            self.assertNotIn("prod_key.pem", raw)
            self.assertNotIn("sk-ant-secret", raw)
            self.assertNotIn(str(home), raw)

            self.assertEqual(len(data["radar_axes"]), 6)
            for ax in data["radar_axes"]:
                self.assertGreaterEqual(ax["score"], 0)
                self.assertLessEqual(ax["score"], 100)

            # --all-time includes 2025 Claude session too
            out_all = tmp_path / "facts_all.json"
            proc_all = subprocess.run(
                [sys.executable, "-I", str(COLLECT), "--home", str(home), "--year", "2026", "--all-time", "--output", str(out_all)],
                env=env,
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc_all.returncode, 0, proc_all.stderr)
            data_all = json.loads(out_all.read_text(encoding="utf-8"))
            h_all = {h["id"]: h for h in data_all["harnesses"]}
            self.assertEqual(h_all["claude"]["sessions"], 3)

    def test_graceful_empty_home_distinct_memes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            empty_home = tmp_path / "empty"
            empty_home.mkdir()
            out = tmp_path / "facts.json"
            proc = subprocess.run(
                [sys.executable, "-I", str(COLLECT), "--home", str(empty_home), "--output", str(out)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["totals"]["tool_calls"], 0)
            self.assertEqual(data["peak_hour"], 0)
            self.assertEqual(len(data["radar_axes"]), 6)
            tags = [m["tag"] for m in data["fallback_persona"]["memes"]]
            self.assertEqual(len(tags), len(set(tags)), f"duplicate fallback memes: {tags}")


if __name__ == "__main__":
    unittest.main()
