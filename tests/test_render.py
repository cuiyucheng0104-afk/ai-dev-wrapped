import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RENDER = ROOT / "scripts" / "render.py"
SCHEMA = ROOT / "schemas" / "persona.schema.json"


def sample_facts() -> dict:
    return {
        "schema_version": "1.0",
        "year": 2026,
        "generated_at": "2026-11-22T08:00:00+08:00",
        "timezone_label": "UTC+8",
        "totals": {
            "sessions": 355,
            "subagent_sessions": 4727,
            "tool_calls": 226665,
            "bash_calls": 160556,
            "bash_share_pct": 70.8,
            "active_days": 88,
            "max_parallel_turn": 15,
            "multi_tool_turn_pct": 23.8,
        },
        "harnesses": [
            {"id": "claude", "name": "Claude Code / Desktop", "detected": True, "sessions": 355, "subagents": 4727, "tool_calls": 226665},
            {"id": "codex", "name": "OpenAI Codex", "detected": True, "sessions": 470, "subagents": 0, "tool_calls": 4602},
        ],
        "hours": [105, 95, 244, 195, 132, 63, 49, 2, 0, 0, 2, 0, 8, 18, 49, 12, 27, 156, 141, 16, 4, 50, 79, 129],
        "night_owl_pct": 61.4,
        "peak_hour": 2,
        "top_tools": [
            {"name": "Bash", "count": 160556, "pct": 70.8},
            {"name": "Read", "count": 25246, "pct": 11.1},
        ],
        "top_models": [{"name": "claude-opus-5", "count": 142151}],
        "bash_dna": {
            "total_bash_calls": 160556,
            "chained_pct": 58.6,
            "piped_pct": 68.7,
            "heredoc_count": 24360,
            "rtk_proxy_count": 3985,
            "top_commands": [
                {"name": "grep", "count": 93953},
                {"name": "git", "count": 51948},
            ],
        },
        "inventory": {
            "skills_installed": 238,
            "agents_installed": 162,
            "plugins_total": 33,
            "plugins_unused": 23,
            "rtk_hook_enabled": True,
            "auto_or_bypass": True,
            "grep_calls": 1,
            "glob_calls": 0,
        },
        "radar_axes": [
            {"key": "orchestration", "label": "编排杠杆", "label_en": "Orchestration", "score": 96},
            {"key": "shell_craft", "label": "终端功底", "label_en": "Shell Craft", "score": 94},
            {"key": "domain_span", "label": "跨界广度", "label_en": "Domain Span", "score": 91},
            {"key": "verification", "label": "工程洁癖", "label_en": "Verification", "score": 84},
            {"key": "night_ops", "label": "夜战耐力", "label_en": "Night Ops", "score": 95},
            {"key": "autonomy", "label": "放权程度", "label_en": "Autonomy", "score": 92},
        ],
        "fallback_persona": {
            "archetype_id": "nightshift-orchestrator",
            "archetype_title": "深夜蜂群总工",
            "archetype_en": "Nightshift Swarm Architect",
            "one_liner": "凌晨两点还在拉 16 棵进程树，只用 Bash 也能打出全栈闭环。",
            "one_liner_en": "02:00 AM is your morning rush hour, spinning swarms with pure Bash.",
            "secondary_badges": ["终端炼金术士", "跨界特种兵"],
            "secondary_badges_en": ["Shell Alchemist", "Multi-Harness"],
            "memes": [
                {
                    "tag": "Grep=1 / Bash=16万",
                    "tag_en": "Grep=1 / Bash=160k",
                    "line": "系统里没给 Grep，于是我用 grep+head+sed 管道硬刚了十六万次。",
                    "line_en": "No Grep tool? grep | head | sed is my native runtime.",
                },
                {
                    "tag": "3,985 次 rtk proxy",
                    "tag_en": "3,985x rtk proxy",
                    "line": "自己装了省 Token 钩子，嫌省过头又亲自喊了四千次撤销压缩。",
                    "line_en": "Installed a token compressor hook, then bypassed it 3,985 times.",
                },
            ],
            "axis_notes": {
                "orchestration": "主会话 355 / 子代理 4,727",
                "shell_craft": "Bash 占比 70.8%",
                "domain_span": "跨量化、渲染与部署",
                "verification": "完成前验证与只读审查",
                "night_ops": "凌晨 2 点早高峰",
                "autonomy": "Auto + Bypass 狂飙",
            },
            "axis_notes_en": {
                "orchestration": "355 main / 4,727 subagents",
                "shell_craft": "70.8% Bash",
                "domain_span": "Quant, rendering & deploy",
                "verification": "Read-only review & tests",
                "night_ops": "02:00 AM rush hour",
                "autonomy": "Auto + Bypass",
            },
        },
    }


class TestRender(unittest.TestCase):
    def test_schema_exists_and_render_with_xss_and_comment_safety(self):
        self.assertTrue(SCHEMA.exists(), "persona.schema.json missing")
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        self.assertIn("required", schema)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facts_p = tmp_path / "facts.json"
            persona_p = tmp_path / "persona.json"
            out_html = tmp_path / "index.html"

            facts_p.write_text(json.dumps(sample_facts()), encoding="utf-8")
            persona = sample_facts()["fallback_persona"].copy()
            # Both </script> and <!-- must produce valid RFC 8259 JSON inside HTML
            persona["one_liner"] = "Test </script><script>alert(1)</script> <!-- comment --> safe"
            persona_p.write_text(json.dumps(persona, ensure_ascii=False), encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, "-I", str(RENDER), "--facts", str(facts_p), "--persona", str(persona_p), "--out", str(out_html), "--lang", "en"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = out_html.read_text(encoding="utf-8")

            self.assertNotIn("</script><script>alert(1)", html)
            self.assertNotIn("<!-- comment -->", html)
            # Extract embedded JSON and verify JSON.parse validity
            m = re.search(r'<script id="wrapped-data" type="application/json">(.*?)</script>', html, re.S)
            self.assertIsNotNone(m)
            parsed = json.loads(m.group(1))
            self.assertIn("<!-- comment -->", parsed["persona"]["one_liner"])

            for forbidden in ("https://cdn", "unpkg.com", "fonts.googleapis.com", "jsdelivr.net"):
                self.assertNotIn(forbidden, html)
            self.assertIn("AudioContext", html)
            self.assertIn("toDataURL", html)
            self.assertIn("drawRoundRect", html)
            self.assertIn("langBtn", html)
            self.assertIn("<svg", html)

    def test_invalid_persona_types_and_single_file_http(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facts_p = tmp_path / "facts.json"
            bad_types_p = tmp_path / "bad_types.json"
            secret_sibling = tmp_path / "secret.txt"
            out_html = tmp_path / "index.html"

            facts_p.write_text(json.dumps(sample_facts()), encoding="utf-8")
            secret_sibling.write_text("TOP_SECRET", encoding="utf-8")
            # Wrong types for secondary_badges, memes, radar_overrides
            bad_types_p.write_text(
                json.dumps({"secondary_badges": "not-a-list", "memes": "not-a-list", "one_liner": 123, "radar_overrides": {"orchestration": True}}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, "-I", str(RENDER), "--facts", str(facts_p), "--persona", str(bad_types_p), "--out", str(out_html)],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            html = out_html.read_text(encoding="utf-8")
            m = re.search(r'<script id="wrapped-data" type="application/json">(.*?)</script>', html, re.S)
            parsed = json.loads(m.group(1))
            self.assertIsInstance(parsed["persona"]["secondary_badges"], list)
            self.assertIsInstance(parsed["persona"]["memes"], list)

            sys.path.insert(0, str(ROOT / "scripts"))
            try:
                import render  # type: ignore
                server, port = render.start_http_server(out_html, port=0)
                t = threading.Thread(target=server.serve_forever, daemon=True)
                t.start()
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                try:
                    with opener.open(f"http://127.0.0.1:{port}/", timeout=3) as resp:
                        self.assertEqual(resp.status, 200)
                        self.assertIn("Nightshift Swarm Architect", resp.read().decode("utf-8"))
                    with opener.open(f"http://127.0.0.1:{port}/favicon.ico", timeout=3) as fav:
                        self.assertEqual(fav.status, 204)
                    # Sibling file & directory exposure must return 404
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        opener.open(f"http://127.0.0.1:{port}/secret.txt", timeout=3)
                    self.assertEqual(ctx.exception.code, 404)
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                sys.path.pop(0)

    def test_daemon_serve_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            facts_p = tmp_path / "facts.json"
            out_html = tmp_path / "site" / "index.html"
            facts_p.write_text(json.dumps(sample_facts()), encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, "-I", str(RENDER), "--facts", str(facts_p), "--out", str(out_html), "--serve", "--daemon"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            url_lines = [l for l in proc.stdout.splitlines() if "serving in background:" in l]
            self.assertTrue(url_lines, f"missing URL in stdout: {proc.stdout}")
            url = url_lines[0].split("serving in background: ")[-1].strip()
            pid_file = Path(tempfile.gettempdir()) / "ai_wrapped_server.pid"
            self.assertTrue(pid_file.exists())
            pid = json.loads(pid_file.read_text(encoding="utf-8"))["pid"]
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(url, timeout=3) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("深夜蜂群总工", resp.read().decode("utf-8"))
            finally:
                try:
                    os.kill(pid, signal.SIGTERM)
                except OSError:
                    pass
                pid_file.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
