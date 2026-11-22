#!/usr/bin/env python3
"""Cross-harness read-only collector for AI Developer Wrapped."""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import re
import sqlite3
import sys
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

# Sanitization patterns (privacy-first: strip IPs, keys, tokens, emails, home paths)
RE_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
RE_TOKEN = re.compile(
    r"\b(?:sk-[A-Za-z0-9_-]{6,}|gh[pousr]_[A-Za-z0-9]{10,}|xox[baprs]-[A-Za-z0-9-]{8,}|AIza[0-9A-Za-z_-]{16,})\b"
)
RE_KEY_PATH = re.compile(r"[^\s'\"]*\.(?:pem|key|p12|pfx)|[^\s'\"]*id_(?:rsa|ed25519|ecdsa)\b", re.I)
RE_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
RE_FRAC_SEC = re.compile(r"(\.\d+)(?=[+-]\d{2}:\d{2}$|$)")

HEREDOC_START = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
ENV_PREFIX = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|[^\s]+)\s+")

SKIP_SHELL_BUILTINS = {
    "{", "}", "fi", "done", "esac", "for", "case", "in", "function",
    "export", "local", "set", "unset", "wait", "sleep", "true", "false",
    "then", "do", "else", "elif", "if", "while", "until", "cd", "echo", "printf", "[", "test",
}


def detect_host_tz_offset() -> float:
    """Detect host local UTC offset in hours (fallback 0.0)."""
    try:
        offset = datetime.datetime.now().astimezone().utcoffset()
        if offset is not None:
            return round(offset.total_seconds() / 3600.0, 2)
    except Exception:
        pass
    return 0.0


def sanitize_text(text: str, home_str: str = "") -> str:
    """Scrub sensitive tokens, IPs, private key paths, emails, and raw home path."""
    if not text:
        return ""
    out = text
    if home_str and home_str != "/":
        out = out.replace(home_str, "~")
    out = RE_TOKEN.sub("<redacted-token>", out)
    out = RE_KEY_PATH.sub("<redacted-key>", out)
    out = RE_IPV4.sub("<redacted-ip>", out)
    out = RE_EMAIL.sub("<redacted-email>", out)
    return out


def parse_iso_dt(ts_str: str, tz_offset_hours: float) -> datetime.datetime | None:
    """Parse ISO-8601 UTC/offset string (Python 3.9+ safe) into local datetime."""
    if not ts_str or not isinstance(ts_str, str):
        return None
    try:
        s = ts_str.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # Python 3.9-3.10 fromisoformat only accepts 0, 3, or 6 fractional digits
        s = RE_FRAC_SEC.sub(lambda m: (m.group(1) + "000000")[:7], s)
        dt = datetime.datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        target_tz = datetime.timezone(datetime.timedelta(hours=tz_offset_hours))
        return dt.astimezone(target_tz)
    except Exception:
        return None


def parse_epoch_dt(epoch_val: float | int, tz_offset_hours: float) -> datetime.datetime | None:
    """Convert Unix seconds or milliseconds into local datetime."""
    if not epoch_val:
        return None
    try:
        val = float(epoch_val)
        if val > 1e12:
            val /= 1000.0
        target_tz = datetime.timezone(datetime.timedelta(hours=tz_offset_hours))
        return datetime.datetime.fromtimestamp(val, tz=datetime.timezone.utc).astimezone(target_tz)
    except Exception:
        return None


def unwrap_command_str(cmd: str) -> str:
    """Unwrap JSON-quoted or shell -lc wrapped command strings."""
    s = cmd.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        try:
            unwrapped = json.loads(s)
            if isinstance(unwrapped, str):
                s = unwrapped.strip()
        except Exception:
            pass
    m = re.match(r"^(?:/bin/)?(?:z?sh|bash)\s+-[a-z]*c\s+(['\"])(.*)\1$", s, flags=re.S)
    if m:
        s = m.group(2)
    return s


def strip_heredocs_and_inline(cmd: str) -> str:
    """Strip heredoc bodies and inline -c/-e code blocks before command tokenization."""
    lines = cmd.splitlines()
    kept: list[str] = []
    delim: str | None = None
    for line in lines:
        if delim is not None:
            if line.strip() == delim:
                delim = None
            continue
        m = HEREDOC_START.search(line)
        if m:
            kept.append(line)
            delim = m.group(1)
            continue
        kept.append(line)

    cleaned = "\n".join(kept)
    cleaned = re.sub(r"(\bpython3?\s+-c\s+)(?:'[^']*'|\"[^\"]*\")", r"\1<CODE>", cleaned, flags=re.S)
    cleaned = re.sub(r"(\bnode\s+(?:-e|--eval)\s+)(?:'[^']*'|\"[^\"]*\")", r"\1<CODE>", cleaned, flags=re.S)
    cleaned = re.sub(r"(\bawk\s+(?:-F\S+\s+)?)(?:'[^']*'|\"[^\"]*\")", r"\1<AWK>", cleaned, flags=re.S)
    cleaned = re.sub(r"(\bsed\s+(?:-[A-Za-z]+\s+)*)(?:'[^']*'|\"[^\"]*\")", r"\1<SED>", cleaned, flags=re.S)
    return cleaned


def split_outside_quotes(text: str) -> list[str]:
    """Split shell text on &&, ||, ;, |, newline outside single/double quotes."""
    parts: list[str] = []
    buf: list[str] = []
    in_sq = False
    in_dq = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and not in_sq and i + 1 < n:
            buf.append(ch)
            buf.append(text[i + 1])
            i += 2
            continue
        if ch == "'" and not in_dq:
            in_sq = not in_sq
            buf.append(ch)
            i += 1
            continue
        if ch == '"' and not in_sq:
            in_dq = not in_dq
            buf.append(ch)
            i += 1
            continue
        if not in_sq and not in_dq:
            if text[i : i + 2] in ("&&", "||"):
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if ch in (";", "|", "\n"):
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append("".join(buf))
    return parts


def extract_bash_verbs(cmd: str) -> list[str]:
    """Extract normalized executable names from a shell command string."""
    if not cmd:
        return []
    cmd = unwrap_command_str(cmd)
    cleaned = strip_heredocs_and_inline(cmd)
    verbs: list[str] = []
    for seg in split_outside_quotes(cleaned):
        seg = seg.strip()
        if not seg or seg.startswith("#"):
            continue
        while True:
            em = ENV_PREFIX.match(seg)
            if not em:
                break
            seg = seg[em.end() :].strip()
        if not seg:
            continue
        toks = seg.split()
        while toks and toks[0] in ("then", "do", "else", "elif", "if", "while", "until", "!", "time", "nohup", "exec", "command"):
            toks = toks[1:]
        if not toks:
            continue
        raw_bin = toks[0].strip("()\"'")
        if not raw_bin:
            continue
        base = os.path.basename(raw_bin) if "/" in raw_bin else raw_bin
        if base.startswith("python3.") or (base.startswith("python") and base != "python3"):
            base = "python3"
        if base in SKIP_SHELL_BUILTINS:
            continue
        verbs.append(base)
    return verbs


def analyze_bash_command(cmd: str, verb_counter: Counter[str], bash_flags: Counter[str]) -> None:
    """Update Bash DNA counters from a single shell command."""
    if not cmd:
        return
    unwrapped = unwrap_command_str(cmd)
    bash_flags["total"] += 1
    if "&&" in unwrapped:
        bash_flags["chained"] += 1
    if "|" in unwrapped:
        bash_flags["piped"] += 1
    if "<<" in unwrapped:
        bash_flags["heredoc"] += 1
    if "rtk proxy" in unwrapped:
        bash_flags["rtk_proxy"] += 1
    if "core.quotepath=false" in unwrapped:
        bash_flags["git_quotepath"] += 1
    if "pytest" in unwrapped or "unittest" in unwrapped or "npm test" in unwrapped or "cargo test" in unwrapped:
        bash_flags["test_cmd"] += 1
    if "git worktree" in unwrapped:
        bash_flags["worktree_cmd"] += 1
    for v in extract_bash_verbs(unwrapped):
        verb_counter[v] += 1


def _year_matches(dt: datetime.datetime | None, target_year: int | None) -> bool:
    if target_year is None or dt is None:
        return True
    return dt.year == target_year


def _scan_claude_file(args: tuple[str, float, int | None]) -> dict[str, Any]:
    """Worker to scan one Claude Code/Desktop JSONL transcript."""
    filepath_str, tz_offset, target_year = args
    p = Path(filepath_str)
    is_sub = "subagents" in p.parts
    session_ep = None
    tools: Counter[str] = Counter()
    models: Counter[str] = Counter()
    verbs: Counter[str] = Counter()
    bflags: Counter[str] = Counter()
    hours: Counter[int] = Counter()
    days: set[str] = set()
    msg_tool_counts: dict[str, int] = {}
    efforts: Counter[str] = Counter()
    has_auto_or_bypass = False
    cwds: set[str] = set()
    matched_year_events = 0
    saw_any_dt = False

    try:
        with p.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                is_asst = '"type":"assistant"' in line or '"type": "assistant"' in line
                is_user = '"type":"user"' in line or '"type": "user"' in line
                if not (is_asst or is_user or (not session_ep and '"entrypoint"' in line)):
                    continue
                if len(line) > 3_000_000 and not is_asst:
                    continue
                try:
                    d = json.loads(line)
                except Exception:
                    continue

                ep = d.get("entrypoint")
                if ep and not session_ep:
                    session_ep = ep

                ts_raw = d.get("timestamp")
                dt = parse_iso_dt(ts_raw, tz_offset) if isinstance(ts_raw, str) else None
                if dt is not None:
                    saw_any_dt = True
                if not _year_matches(dt, target_year):
                    continue
                matched_year_events += 1

                pm = d.get("permissionMode")
                if pm in ("auto", "bypassPermissions"):
                    has_auto_or_bypass = True

                cwd = d.get("cwd")
                if cwd and isinstance(cwd, str):
                    cwds.add(os.path.basename(cwd.rstrip("/")) or "root")

                if dt:
                    days.add(dt.strftime("%Y-%m-%d"))
                    if is_user and not is_sub:
                        hours[dt.hour] += 1

                if d.get("type") != "assistant":
                    continue

                eff = d.get("perTurnEffort") or d.get("effort")
                if eff:
                    efforts[str(eff)] += 1

                msg = d.get("message") or {}
                model = d.get("requestedModel") or msg.get("model")
                if model and model != "<synthetic>":
                    models[str(model)] += 1

                content = msg.get("content")
                if not isinstance(content, list):
                    continue

                mid = str(msg.get("id") or d.get("requestRef") or d.get("uuid") or "")
                turn_tu = 0
                for blk in content:
                    if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                        continue
                    turn_tu += 1
                    tname = str(blk.get("name") or "unknown")
                    tools[tname] += 1
                    inp = blk.get("input") or {}
                    if tname == "Bash" and isinstance(inp, dict):
                        cmd = inp.get("command")
                        if isinstance(cmd, str):
                            analyze_bash_command(cmd, verbs, bflags)

                if mid and turn_tu:
                    msg_tool_counts[mid] = msg_tool_counts.get(mid, 0) + turn_tu
    except Exception:
        pass

    active_in_year = matched_year_events > 0 or not saw_any_dt
    return {
        "ep": session_ep or "unknown",
        "is_sub": is_sub,
        "active_in_year": active_in_year,
        "tools": tools,
        "models": models,
        "verbs": verbs,
        "bflags": bflags,
        "hours": hours,
        "days": days,
        "turn_sizes": list(msg_tool_counts.values()),
        "has_auto": has_auto_or_bypass,
        "efforts": efforts,
        "cwds": cwds,
    }


def collect_claude(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect Claude Code & Claude Desktop metrics."""
    claude_dir = home / ".claude"
    proj_dir = claude_dir / "projects"
    res: dict[str, Any] = {
        "detected": False,
        "sessions": 0,
        "subagents": 0,
        "entrypoints": Counter(),
        "tools": Counter(),
        "models": Counter(),
        "verbs": Counter(),
        "bflags": Counter(),
        "hours": Counter(),
        "days": set(),
        "turn_sizes": [],
        "auto_or_bypass": False,
        "efforts": Counter(),
        "projects": set(),
        "inventory": {
            "skills_installed": 0,
            "agents_installed": 0,
            "plugins_total": 0,
            "plugins_unused": 0,
            "rtk_hook_enabled": False,
        },
        "skill_usage": Counter(),
    }

    if not claude_dir.exists() and not (home / ".claude.json").exists():
        return res

    res["detected"] = True
    files = [str(p) for p in proj_dir.rglob("*.jsonl")] if proj_dir.exists() else []
    seen_session_stems = {Path(f).stem for f in files if "subagents" not in Path(f).parts}

    if files:
        tasks = [(f, tz_offset, target_year) for f in files]
        results = []
        if len(tasks) >= 30:
            try:
                with ProcessPoolExecutor(max_workers=min(8, os.cpu_count() or 4)) as ex:
                    results = list(ex.map(_scan_claude_file, tasks, chunksize=32))
            except Exception:
                results = [_scan_claude_file(t) for t in tasks]
        else:
            results = [_scan_claude_file(t) for t in tasks]

        for r in results:
            if not r["active_in_year"]:
                continue
            if r["is_sub"]:
                res["subagents"] += 1
            else:
                res["sessions"] += 1
                res["entrypoints"][r["ep"]] += 1
            res["tools"].update(r["tools"])
            res["models"].update(r["models"])
            res["verbs"].update(r["verbs"])
            res["bflags"].update(r["bflags"])
            res["hours"].update(r["hours"])
            res["days"].update(r["days"])
            res["turn_sizes"].extend(r["turn_sizes"])
            res["efforts"].update(r["efforts"])
            res["projects"].update(r["cwds"])
            if r["has_auto"]:
                res["auto_or_bypass"] = True

    hist_p = claude_dir / "history.jsonl"
    if hist_p.exists():
        hist_sids: set[str] = set()
        try:
            with hist_p.open("r", encoding="utf-8", errors="ignore") as hf:
                for line in hf:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    dt = parse_epoch_dt(d.get("timestamp", 0), tz_offset)
                    if not _year_matches(dt, target_year):
                        continue
                    sid = d.get("sessionId")
                    if sid and sid not in seen_session_stems:
                        hist_sids.add(sid)
                        if dt:
                            res["hours"][dt.hour] += 1
                            res["days"].add(dt.strftime("%Y-%m-%d"))
                    proj = d.get("project")
                    if isinstance(proj, str) and proj:
                        res["projects"].add(os.path.basename(proj.rstrip("/")) or "root")
        except Exception as e:
            warnings.append(f"claude history.jsonl unreadable: {type(e).__name__}")
        if hist_sids:
            res["sessions"] += len(hist_sids)
            res["entrypoints"]["cli-history"] += len(hist_sids)

    for sp in (claude_dir / "settings.json", claude_dir / "settings.local.json"):
        if sp.exists():
            try:
                sd = json.loads(sp.read_text(encoding="utf-8", errors="ignore"))
                if sd.get("permissions", {}).get("defaultMode") in ("auto", "bypassPermissions"):
                    res["auto_or_bypass"] = True
                if "rtk hook" in json.dumps(sd.get("hooks", {})):
                    res["inventory"]["rtk_hook_enabled"] = True
            except Exception:
                pass

    cj = home / ".claude.json"
    if cj.exists():
        try:
            cd = json.loads(cj.read_text(encoding="utf-8", errors="ignore"))
            pu = cd.get("pluginUsage", {})
            if isinstance(pu, dict):
                res["inventory"]["plugins_total"] = len(pu)
                res["inventory"]["plugins_unused"] = sum(
                    1 for v in pu.values() if isinstance(v, dict) and v.get("usageCount", 0) == 0
                )
            su = cd.get("skillUsage", {})
            if isinstance(su, dict):
                for sk, sv in su.items():
                    if isinstance(sv, dict):
                        res["skill_usage"][sk] += int(sv.get("usageCount", 0))
        except Exception:
            pass

    skills_dir = claude_dir / "skills"
    if skills_dir.exists():
        try:
            res["inventory"]["skills_installed"] = sum(1 for x in skills_dir.iterdir() if x.is_dir())
        except Exception:
            pass
    agents_dir = claude_dir / "agents"
    if agents_dir.exists():
        try:
            res["inventory"]["agents_installed"] = sum(1 for x in agents_dir.iterdir() if x.is_file())
        except Exception:
            pass

    desk_cfg = home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    try:
        if desk_cfg.exists():
            dd = json.loads(desk_cfg.read_text(encoding="utf-8", errors="ignore"))
            prefs = dd.get("preferences", {})
            if prefs.get("bypassPermissionsOptInByAccount") or prefs.get("chicagoPreferredMode") == "full_control":
                res["auto_or_bypass"] = True
    except Exception:
        pass

    return res


def collect_codex(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect OpenAI Codex sessions & tool calls via immutable SQLite or JSONL fallback."""
    codex_dir = home / ".codex"
    res: dict[str, Any] = {
        "detected": False,
        "sessions": 0,
        "subagents": 0,
        "tools": Counter(),
        "models": Counter(),
        "verbs": Counter(),
        "bflags": Counter(),
        "hours": Counter(),
        "days": set(),
        "projects": set(),
        "auto_or_bypass": False,
    }
    if not codex_dir.exists():
        return res
    res["detected"] = True

    state_db = codex_dir / "state_5.sqlite"
    hist_db = codex_dir / "thread_history_1.sqlite"

    if state_db.exists():
        try:
            con = sqlite3.connect(f"file:{state_db}?immutable=1", uri=True)
            for row in con.execute("SELECT created_at_ms, cwd, model, approval_mode, agent_role FROM threads"):
                dt = parse_epoch_dt(row[0] or 0, tz_offset)
                if not _year_matches(dt, target_year):
                    continue
                if row[4]:
                    res["subagents"] += 1
                else:
                    res["sessions"] += 1
                if dt:
                    res["hours"][dt.hour] += 1
                    res["days"].add(dt.strftime("%Y-%m-%d"))
                if row[1]:
                    res["projects"].add(os.path.basename(str(row[1]).rstrip("/")) or "root")
                if row[2]:
                    res["models"][str(row[2])] += 1
                if row[3] in ("never", "auto-edit", "full-auto"):
                    res["auto_or_bypass"] = True
            con.close()
        except Exception as e:
            warnings.append(f"codex state_5.sqlite read failed: {type(e).__name__}")

    if hist_db.exists():
        try:
            con = sqlite3.connect(f"file:{hist_db}?immutable=1", uri=True)
            for itype, created_ms, ijson in con.execute(
                "SELECT item_type, created_at_ms, item_json FROM thread_items WHERE item_type NOT IN ('agentMessage','reasoning','contextCompaction')"
            ):
                dt = parse_epoch_dt(created_ms or 0, tz_offset)
                if not _year_matches(dt, target_year):
                    continue
                if itype == "userMessage":
                    if dt:
                        res["hours"][dt.hour] += 1
                        res["days"].add(dt.strftime("%Y-%m-%d"))
                    continue
                if itype == "commandExecution":
                    res["tools"]["Bash"] += 1
                    try:
                        obj = json.loads(ijson)
                        cmd = obj.get("command") or ""
                        if isinstance(cmd, str):
                            analyze_bash_command(cmd, res["verbs"], res["bflags"])
                    except Exception:
                        pass
                elif itype == "mcpToolCall":
                    try:
                        obj = json.loads(ijson)
                        srv = obj.get("server", "mcp")
                        tl = obj.get("tool", "call")
                        res["tools"][f"mcp__{srv}__{tl}"] += 1
                    except Exception:
                        res["tools"]["mcp__codex__tool"] += 1
                elif itype == "fileChange":
                    res["tools"]["Edit"] += 1
                elif itype == "webSearch":
                    res["tools"]["WebSearch"] += 1
                elif itype == "collabAgentToolCall":
                    res["tools"]["Agent"] += 1
                elif itype in ("imageView", "imageGeneration"):
                    res["tools"][itype] += 1
            con.close()
        except Exception as e:
            warnings.append(f"codex thread_history_1.sqlite read failed: {type(e).__name__}")

    if res["sessions"] == 0:
        for folder in (codex_dir / "sessions", codex_dir / "archived_sessions"):
            if not folder.exists():
                continue
            for jf in folder.rglob("*.jsonl"):
                sess_added = False
                try:
                    with jf.open("r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            if '"timestamp"' not in line:
                                continue
                            try:
                                d = json.loads(line)
                            except Exception:
                                continue
                            dt = parse_iso_dt(d.get("timestamp", ""), tz_offset)
                            if not _year_matches(dt, target_year):
                                continue
                            if dt:
                                res["days"].add(dt.strftime("%Y-%m-%d"))
                                if d.get("type") == "session_meta":
                                    res["hours"][dt.hour] += 1
                            if not sess_added:
                                res["sessions"] += 1
                                sess_added = True
                except Exception:
                    pass

    return res


def collect_antigravity(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect Google Antigravity conversation transcripts."""
    brain = home / ".gemini" / "antigravity" / "brain"
    res: dict[str, Any] = {
        "detected": False,
        "sessions": 0,
        "tools": Counter(),
        "verbs": Counter(),
        "bflags": Counter(),
        "hours": Counter(),
        "days": set(),
        "turn_sizes": [],
    }
    if not brain.exists():
        return res
    files = list(brain.glob("*/.system_generated/logs/transcript.jsonl"))
    if not files:
        return res
    res["detected"] = True
    for tf in files:
        sess_active = False
        try:
            with tf.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    dt = parse_iso_dt(d.get("created_at", ""), tz_offset)
                    if not _year_matches(dt, target_year):
                        continue
                    sess_active = True
                    if dt:
                        res["days"].add(dt.strftime("%Y-%m-%d"))
                        if d.get("type") == "USER_INPUT":
                            res["hours"][dt.hour] += 1
                    if d.get("type") == "PLANNER_RESPONSE":
                        tcalls = [tc for tc in (d.get("tool_calls") or []) if isinstance(tc, dict)]
                        if tcalls:
                            res["turn_sizes"].append(len(tcalls))
                        for tc in tcalls:
                            name = str(tc.get("name") or "tool")
                            if name == "run_command":
                                res["tools"]["Bash"] += 1
                                args = tc.get("args") or tc.get("arguments") or {}
                                if isinstance(args, dict):
                                    cmd = args.get("CommandLine") or args.get("command")
                                    if isinstance(cmd, str):
                                        analyze_bash_command(cmd, res["verbs"], res["bflags"])
                            else:
                                res["tools"][name] += 1
        except Exception as e:
            warnings.append(f"antigravity transcript read failed: {type(e).__name__}")
        if sess_active:
            res["sessions"] += 1
    return res


def collect_kimi(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect Kimi CLI sessions."""
    sess_dir = home / ".kimi" / "sessions"
    res: dict[str, Any] = {
        "detected": False,
        "sessions": 0,
        "tools": Counter(),
        "verbs": Counter(),
        "bflags": Counter(),
        "hours": Counter(),
        "days": set(),
    }
    if not sess_dir.exists():
        return res
    wire_files = list(sess_dir.rglob("wire.jsonl"))
    ctx_files = list(sess_dir.rglob("context.jsonl"))
    if not wire_files and not ctx_files:
        return res
    res["detected"] = True

    active_session_dirs: set[Path] = set()
    for wf in wire_files:
        matched = False
        saw_dt = False
        try:
            with wf.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"TurnBegin"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    dt = parse_epoch_dt(d.get("timestamp", 0), tz_offset)
                    if dt is not None:
                        saw_dt = True
                    if not _year_matches(dt, target_year):
                        continue
                    matched = True
                    if dt:
                        res["hours"][dt.hour] += 1
                        res["days"].add(dt.strftime("%Y-%m-%d"))
        except Exception as e:
            warnings.append(f"kimi wire.jsonl read failed: {type(e).__name__}")
        if matched or not saw_dt:
            active_session_dirs.add(wf.parent)

    for cf in ctx_files:
        if cf.parent not in active_session_dirs and wire_files:
            # Skip sessions whose wire.jsonl existed and belonged to another year
            if (cf.parent / "wire.jsonl").exists():
                continue
        active_session_dirs.add(cf.parent)
        try:
            with cf.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"tool_calls"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    for tc in d.get("tool_calls") or []:
                        fn = (tc.get("function") or {}) if isinstance(tc, dict) else {}
                        tname = str(fn.get("name") or "tool")
                        if tname in ("Shell", "Bash", "bash"):
                            res["tools"]["Bash"] += 1
                            try:
                                args = json.loads(fn.get("arguments") or "{}")
                                cmd = args.get("command") or ""
                                if isinstance(cmd, str):
                                    analyze_bash_command(cmd, res["verbs"], res["bflags"])
                            except Exception:
                                pass
                        else:
                            res["tools"][tname] += 1
        except Exception:
            pass

    res["sessions"] = len(active_session_dirs)
    return res


_SHELL_TOOL_NAMES = {
    "bash", "shell", "exec", "run_command", "run_terminal_cmd",
    "run_terminal_command", "execute_command", "terminal", "powershell", "sh", "zsh",
}


def _new_harness_res(detected: bool = False) -> dict[str, Any]:
    return {
        "detected": detected,
        "sessions": 0,
        "subagents": 0,
        "tools": Counter(),
        "models": Counter(),
        "verbs": Counter(),
        "bflags": Counter(),
        "hours": Counter(),
        "days": set(),
        "turn_sizes": [],
        "projects": set(),
        "auto_or_bypass": False,
    }


def _record_tool(res: dict[str, Any], raw_name: Any, raw_args: Any = None) -> None:
    """Normalize tool usage and extract Bash DNA across arbitrary agent schemas."""
    name = str(raw_name or "tool").strip() or "tool"
    if name.lower() in _SHELL_TOOL_NAMES:
        res["tools"]["Bash"] += 1
        args = raw_args
        if isinstance(args, str):
            try:
                parsed = json.loads(args)
                if isinstance(parsed, dict):
                    args = parsed
            except Exception:
                analyze_bash_command(args, res["verbs"], res["bflags"])
                return
        if isinstance(args, dict):
            for key in ("command", "CommandLine", "cmd", "script", "input"):
                cmd = args.get(key)
                if isinstance(cmd, str) and cmd.strip():
                    analyze_bash_command(cmd, res["verbs"], res["bflags"])
                    break
    else:
        res["tools"][name] += 1


def _parse_any_dt(val: Any, tz_offset: float) -> datetime.datetime | None:
    if isinstance(val, (int, float)) and val > 0:
        return parse_epoch_dt(val, tz_offset)
    if isinstance(val, str) and val.strip():
        if val.strip().isdigit():
            return parse_epoch_dt(float(val.strip()), tz_offset)
        return parse_iso_dt(val, tz_offset)
    return None


def _scan_openclaw_root(
    agents_dir: Path, tz_offset: float, target_year: int | None, warnings: list[str], label: str
) -> dict[str, Any]:
    """Scan OpenClaw-compatible agents/*/sessions/*.jsonl stores."""
    res = _new_harness_res(False)
    if not agents_dir.exists():
        return res
    files = list(agents_dir.glob("*/sessions/*.jsonl"))
    if not files:
        return res
    res["detected"] = True
    for sf in files:
        sess_active = False
        try:
            with sf.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    dt = _parse_any_dt(d.get("timestamp", ""), tz_offset)
                    if not _year_matches(dt, target_year):
                        continue
                    sess_active = True
                    if dt:
                        res["days"].add(dt.strftime("%Y-%m-%d"))
                    if d.get("type") == "model_change" and d.get("modelId"):
                        res["models"][str(d["modelId"])] += 1
                    if d.get("type") == "message":
                        msg = d.get("message") or {}
                        if msg.get("role") == "user" and dt:
                            res["hours"][dt.hour] += 1
                        if msg.get("role") == "assistant":
                            if msg.get("model"):
                                res["models"][str(msg["model"])] += 1
                            for blk in msg.get("content") or []:
                                if isinstance(blk, dict) and blk.get("type") in ("toolCall", "tool_use"):
                                    _record_tool(res, blk.get("name"), blk.get("arguments") or blk.get("input"))
        except Exception as e:
            warnings.append(f"{label} session read failed: {type(e).__name__}")
        if sess_active:
            res["sessions"] += 1
    return res


def collect_openclaw(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect OpenClaw agent transcripts."""
    return _scan_openclaw_root(home / ".openclaw" / "agents", tz_offset, target_year, warnings, "openclaw")


def collect_autoclaw(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect AutoClaw sessions & background task runs."""
    ac_dir = home / ".openclaw-autoclaw"
    res = _scan_openclaw_root(ac_dir / "agents", tz_offset, target_year, warnings, "autoclaw")
    db = ac_dir / "tasks" / "runs.sqlite"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
            for row in con.execute("SELECT created_at, task_kind FROM task_runs"):
                dt = parse_epoch_dt(row[0] or 0, tz_offset)
                if not _year_matches(dt, target_year):
                    continue
                res["detected"] = True
                res["subagents"] += 1
                if dt:
                    res["hours"][dt.hour] += 1
                    res["days"].add(dt.strftime("%Y-%m-%d"))
            con.close()
        except Exception as e:
            warnings.append(f"autoclaw runs db failed: {type(e).__name__}")
    res["detected"] = res["sessions"] > 0 or res["subagents"] > 0 or sum(res["tools"].values()) > 0
    return res


def collect_cursor(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect Cursor tracking DB & agent-transcripts JSONL files."""
    cur_dir = home / ".cursor"
    res: dict[str, Any] = {
        "detected": False,
        "sessions": 0,
        "tools": Counter(),
        "models": Counter(),
        "verbs": Counter(),
        "bflags": Counter(),
        "hours": Counter(),
        "days": set(),
    }
    if not cur_dir.exists():
        return res
    db = cur_dir / "ai-tracking" / "ai-code-tracking.db"
    proj_dir = cur_dir / "projects"
    transcripts: list[Path] = []
    if proj_dir.exists():
        for p in proj_dir.rglob("*.jsonl"):
            if p.is_file() and "agent-transcripts" in p.parts:
                transcripts.append(p)

    if not db.exists() and not transcripts:
        return res
    res["detected"] = True

    for tf in transcripts:
        try:
            mtime_dt = parse_epoch_dt(tf.stat().st_mtime, tz_offset)
            if not _year_matches(mtime_dt, target_year):
                continue
            res["sessions"] += 1
            if mtime_dt:
                res["days"].add(mtime_dt.strftime("%Y-%m-%d"))
                res["hours"][mtime_dt.hour] += 1
            with tf.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if '"tool_use"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    msg = d.get("message") or {}
                    for blk in msg.get("content") or []:
                        if not isinstance(blk, dict) or blk.get("type") != "tool_use":
                            continue
                        tname = str(blk.get("name") or "tool")
                        if tname in ("Shell", "Bash", "bash", "run_terminal_cmd"):
                            res["tools"]["Bash"] += 1
                            inp = blk.get("input") or {}
                            if isinstance(inp, dict) and isinstance(inp.get("command"), str):
                                analyze_bash_command(inp["command"], res["verbs"], res["bflags"])
                        else:
                            res["tools"][tname] += 1
        except Exception as e:
            warnings.append(f"cursor transcript read failed: {type(e).__name__}")

    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
            rows = con.execute("SELECT timestamp, model FROM ai_code_hashes").fetchall()
            matched_rows = 0
            for ts_ms, model in rows:
                dt = parse_epoch_dt(ts_ms or 0, tz_offset)
                if not _year_matches(dt, target_year):
                    continue
                matched_rows += 1
                if dt:
                    res["hours"][dt.hour] += 1
                    res["days"].add(dt.strftime("%Y-%m-%d"))
                if model:
                    res["models"][str(model)] += 1
                res["tools"]["Edit"] += 1
            if matched_rows and res["sessions"] == 0:
                res["sessions"] = 1
            con.close()
        except Exception as e:
            warnings.append(f"cursor tracking db read failed: {type(e).__name__}")
    return res


_IDE_APPS = (
    "Code", "Code - Insiders", "Cursor", "Windsurf",
    "Trae", "Trae CN", "Kiro", "Qoder", "VSCodium", "Positron",
)
_SKIP_WALK_DIRS = {
    "skills", "bundled", "Cache", "CachedData", "GPUCache", "Code Cache",
    "Crashpad", "Service Worker", "blob_storage", "node_modules", ".git",
    "__pycache__", "extensions", "bin", "dist", "build", "logs",
}
_SESSION_SUBDIRS = (
    "sessions", "session-state", "projects", "chats", "threads",
    "tasks", "history", "conversations", "agent-transcripts", "events", "storage",
)


def _ide_user_roots(home: Path, apps: tuple[str, ...] = _IDE_APPS) -> list[Path]:
    roots: list[Path] = []
    for base in (
        home / "Library" / "Application Support",
        home / ".config",
        home / "AppData" / "Roaming",
    ):
        if not base.exists():
            continue
        for app in apps:
            u = base / app / "User"
            if u.exists():
                roots.append(u)
    return roots


def _ingest_generic_obj(
    obj: Any, res: dict[str, Any], tz_offset: float, target_year: int | None, _depth: int = 0
) -> tuple[bool, bool]:
    """Extract timestamps, models, and tool calls from heterogeneous agent JSON shapes."""
    if _depth > 5 or not isinstance(obj, (dict, list)):
        return False, False
    if isinstance(obj, list):
        act, saw = False, False
        for item in obj[:2000]:
            a, s = _ingest_generic_obj(item, res, tz_offset, target_year, _depth + 1)
            act = act or a
            saw = saw or s
        return act, saw

    dt: datetime.datetime | None = None
    for tk in ("timestamp", "createdAt", "created_at", "creationDate", "startTime", "ts", "time", "date"):
        if tk in obj:
            raw_t = obj.get(tk)
            if tk == "time" and isinstance(raw_t, dict):
                raw_t = raw_t.get("created") or raw_t.get("start")
            dt = _parse_any_dt(raw_t, tz_offset)
            if dt:
                break
    saw_dt = dt is not None
    active = _year_matches(dt, target_year)

    if active and dt:
        res["days"].add(dt.strftime("%Y-%m-%d"))
        if obj.get("role") == "user" or obj.get("type") in ("user", "user.message", "prompt"):
            res["hours"][dt.hour] += 1

    for mk in ("model", "modelId", "model_id", "requestedModel", "selectedModel", "modelName"):
        mv = obj.get(mk)
        if active and isinstance(mv, str) and mv.strip() and len(mv) < 120:
            res["models"][mv.strip()] += 1
            break

    for pk in ("cwd", "workspace", "projectPath", "project"):
        pv = obj.get(pk)
        if active and isinstance(pv, str) and pv.strip():
            res["projects"].add(pv.strip())

    # Direct single tool-use / OpenCode tool object
    if active and obj.get("type") == "tool" and obj.get("tool"):
        st_obj = obj.get("state") if isinstance(obj.get("state"), dict) else {}
        _record_tool(res, obj.get("tool"), st_obj.get("input") or obj.get("input"))
    elif active and obj.get("type") in ("tool_use", "toolCall", "function_call", "tool_call") and (obj.get("name") or obj.get("toolName")):
        _record_tool(res, obj.get("name") or obj.get("toolName"), obj.get("input") or obj.get("arguments") or obj.get("args"))

    # Nested functionCall (Gemini style)
    if active and isinstance(obj.get("functionCall"), dict):
        fc = obj["functionCall"]
        _record_tool(res, fc.get("name"), fc.get("args"))

    # Tool lists (OpenAI / Copilot / Gemini CLI)
    if active:
        for list_key in ("tool_calls", "toolCalls", "toolRequests"):
            tcs = obj.get(list_key)
            if isinstance(tcs, list):
                turn_n = 0
                for tc in tcs:
                    if not isinstance(tc, dict):
                        continue
                    turn_n += 1
                    fn = tc.get("function") if isinstance(tc.get("function"), dict) else tc
                    _record_tool(res, fn.get("name") or fn.get("toolName"), fn.get("arguments") or fn.get("args") or fn.get("input"))
                if turn_n:
                    res["turn_sizes"].append(turn_n)

    # Recurse selectively into known conversation containers
    for ck in ("message", "messages", "content", "parts", "requests", "items", "turns", "data", "v"):
        sub = obj.get(ck)
        if isinstance(sub, (dict, list)):
            a, s = _ingest_generic_obj(sub, res, tz_offset, target_year, _depth + 1)
            active = active or a
            saw_dt = saw_dt or s
    return active, saw_dt


def _scan_json_or_jsonl_file(
    fp: Path, res: dict[str, Any], tz_offset: float, target_year: int | None
) -> bool:
    """Parse one JSON (<=25MB) or JSONL (<=100MB stream) transcript cleanly."""
    try:
        st = fp.stat()
        max_bytes = 25 * 1024 * 1024 if fp.suffix == ".json" else 100 * 1024 * 1024
        if st.st_size == 0 or st.st_size > max_bytes:
            return False
        mtime_dt = parse_epoch_dt(st.st_mtime, tz_offset)
    except OSError:
        return False

    fres = _new_harness_res(False)
    matched = False
    saw_dt = False
    if fp.suffix == ".json":
        try:
            data = json.loads(fp.read_text(encoding="utf-8", errors="ignore"))
            matched, saw_dt = _ingest_generic_obj(data, fres, tz_offset, target_year)
        except Exception:
            return False
    else:
        try:
            with fp.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    a, s = _ingest_generic_obj(d, fres, tz_offset, target_year)
                    matched = matched or a
                    saw_dt = saw_dt or s
        except Exception:
            return False

    if not saw_dt and not _year_matches(mtime_dt, target_year):
        return False
    if not matched and saw_dt:
        return False

    for ck in ("tools", "models", "verbs", "bflags", "hours"):
        res[ck].update(fres[ck])
    res["days"].update(fres["days"])
    res["projects"].update(fres["projects"])
    res["turn_sizes"].extend(fres["turn_sizes"])
    if not saw_dt and mtime_dt:
        res["days"].add(mtime_dt.strftime("%Y-%m-%d"))
    if not fres["hours"] and mtime_dt:
        res["hours"][mtime_dt.hour] += 1
    return True


def collect_copilot(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect GitHub Copilot CLI (~/.copilot) & VS Code Copilot Chat sessions."""
    res = _new_harness_res(False)
    cop_dir = home / ".copilot"

    # 1. Copilot CLI session-state/*/events.jsonl
    state_dir = cop_dir / "session-state"
    if state_dir.exists():
        for ef in state_dir.glob("*/events.jsonl"):
            sess_active = False
            saw_dt = False
            seen_call_ids: set[str] = set()
            turn_n = 0
            try:
                with ef.open("r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            d = json.loads(line)
                        except Exception:
                            continue
                        dt = _parse_any_dt(d.get("timestamp", ""), tz_offset)
                        if dt:
                            saw_dt = True
                        if not _year_matches(dt, target_year):
                            continue
                        sess_active = True
                        if dt:
                            res["days"].add(dt.strftime("%Y-%m-%d"))
                        ev_type = d.get("type")
                        data = d.get("data") if isinstance(d.get("data"), dict) else {}
                        if ev_type in ("session.start", "user.message"):
                            if ev_type == "user.message" and dt:
                                res["hours"][dt.hour] += 1
                            if data.get("selectedModel"):
                                res["models"][str(data["selectedModel"])] += 1
                        elif ev_type == "assistant.turn_start":
                            turn_n = 0
                        elif ev_type == "assistant.turn_end":
                            if turn_n:
                                res["turn_sizes"].append(turn_n)
                            turn_n = 0
                        elif ev_type == "tool.execution_start":
                            cid = str(data.get("toolCallId") or "")
                            if cid:
                                seen_call_ids.add(cid)
                            turn_n += 1
                            if data.get("model"):
                                res["models"][str(data["model"])] += 1
                            _record_tool(res, data.get("toolName"), data.get("arguments"))
                        elif ev_type == "assistant.message":
                            if data.get("model"):
                                res["models"][str(data["model"])] += 1
                            for tr in data.get("toolRequests") or []:
                                if not isinstance(tr, dict):
                                    continue
                                cid = str(tr.get("toolCallId") or "")
                                if cid and cid in seen_call_ids:
                                    continue
                                if cid:
                                    seen_call_ids.add(cid)
                                turn_n += 1
                                _record_tool(res, tr.get("name"), tr.get("arguments"))
            except Exception as e:
                warnings.append(f"copilot events read failed: {type(e).__name__}")
            if sess_active:
                res["sessions"] += 1

    # 2. VS Code Copilot Chat sessions
    for uroot in _ide_user_roots(home, ("Code", "Code - Insiders", "VSCodium")):
        ws = uroot / "workspaceStorage"
        if not ws.exists():
            continue
        for cf in list(ws.glob("*/chatSessions/*.jsonl")) + list(ws.glob("*/chatSessions/*.json")):
            if _scan_json_or_jsonl_file(cf, res, tz_offset, target_year):
                res["sessions"] += 1

    res["detected"] = res["sessions"] > 0 or sum(res["tools"].values()) > 0
    return res


def collect_gemini_cli(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect Google Gemini CLI sessions (~/.gemini/tmp/*/chats, ~/.gemini/history)."""
    res = _new_harness_res(False)
    gem = home / ".gemini"
    matched_proj_dirs: set[Path] = set()
    for pat in ("tmp/*/chats/*.json", "history/*.json", "history/*.jsonl"):
        for fp in gem.glob(pat):
            if "antigravity" in fp.parts:
                continue
            if _scan_json_or_jsonl_file(fp, res, tz_offset, target_year):
                res["sessions"] += 1
                if fp.parent.name == "chats":
                    matched_proj_dirs.add(fp.parent.parent)
    for fp in gem.glob("tmp/*/logs.json"):
        if "antigravity" in fp.parts or fp.parent in matched_proj_dirs:
            continue
        if _scan_json_or_jsonl_file(fp, res, tz_offset, target_year):
            res["sessions"] += 1
    res["detected"] = res["sessions"] > 0 or sum(res["tools"].values()) > 0
    return res


def collect_ide_extension_agent(
    home: Path,
    tz_offset: float,
    target_year: int | None,
    warnings: list[str],
    ext_ids: tuple[str, ...],
    dotdirs: tuple[str, ...],
) -> dict[str, Any]:
    """Collect Cline, Roo Code, and Kilo Code task conversation histories."""
    res = _new_harness_res(False)
    task_roots: list[Path] = []
    for uroot in _ide_user_roots(home):
        for eid in ext_ids:
            t = uroot / "globalStorage" / eid / "tasks"
            if t.exists():
                task_roots.append(t)
    for dd in dotdirs:
        for sub in ("tasks", "sessions", "history"):
            p = home / dd / sub
            if p.exists():
                task_roots.append(p)
    for root in task_roots:
        for child in root.iterdir():
            if child.is_dir():
                hist = child / "api_conversation_history.json"
                if hist.exists() and _scan_json_or_jsonl_file(hist, res, tz_offset, target_year):
                    res["sessions"] += 1
            elif child.suffix in (".json", ".jsonl"):
                if _scan_json_or_jsonl_file(child, res, tz_offset, target_year):
                    res["sessions"] += 1
    res["detected"] = res["sessions"] > 0 or sum(res["tools"].values()) > 0
    return res


def collect_opencode(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect OpenCode JSON storage and SQLite sessions."""
    res = _new_harness_res(False)
    oc_dir = home / ".local" / "share" / "opencode"
    sess_dir = oc_dir / "storage" / "session"
    if sess_dir.exists():
        for sf in sess_dir.rglob("*.json"):
            if _scan_json_or_jsonl_file(sf, res, tz_offset, target_year):
                res["sessions"] += 1
    for sub in ("message", "part"):
        sd = oc_dir / "storage" / sub
        if sd.exists():
            for mf in list(sd.rglob("*.json"))[:1000]:
                _scan_json_or_jsonl_file(mf, res, tz_offset, target_year)
    db = oc_dir / "opencode.db"
    if db.exists() and res["sessions"] == 0:
        try:
            con = sqlite3.connect(f"file:{db}?immutable=1", uri=True)
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "session" in tables:
                for row in con.execute("SELECT time_created FROM session"):
                    dt = parse_epoch_dt(row[0] or 0, tz_offset)
                    if _year_matches(dt, target_year):
                        res["sessions"] += 1
                        if dt:
                            res["hours"][dt.hour] += 1
                            res["days"].add(dt.strftime("%Y-%m-%d"))
            if "part" in tables:
                for row in con.execute("SELECT data, time_created FROM part LIMIT 5000"):
                    dt = parse_epoch_dt(row[1] or 0, tz_offset)
                    if not _year_matches(dt, target_year):
                        continue
                    try:
                        pd = json.loads(row[0] or "{}")
                        if isinstance(pd, dict) and pd.get("type") == "tool":
                            _record_tool(res, pd.get("tool"), (pd.get("state") or {}).get("input"))
                    except Exception:
                        pass
            con.close()
        except Exception as e:
            warnings.append(f"opencode db read failed: {type(e).__name__}")
    res["detected"] = res["sessions"] > 0 or sum(res["tools"].values()) > 0
    return res


def collect_windsurf_continue_goose_aider(
    home: Path, tz_offset: float, target_year: int | None, warnings: list[str]
) -> list[tuple[str, str, dict[str, Any]]]:
    """Collect Windsurf, Continue, Goose, and Aider harnesses."""
    out: list[tuple[str, str, dict[str, Any]]] = []

    # 1. Windsurf (Cascade + Windsurf IDE chatSessions; never decode binary .pb contents)
    ws_res = _new_harness_res(False)
    cas = home / ".codeium" / "windsurf" / "cascade"
    if cas.exists():
        for cf in cas.iterdir():
            if not cf.is_file():
                continue
            if cf.suffix in (".json", ".jsonl"):
                if _scan_json_or_jsonl_file(cf, ws_res, tz_offset, target_year):
                    ws_res["sessions"] += 1
            elif cf.suffix == ".pb" and cf.stat().st_size > 64:
                dt = parse_epoch_dt(cf.stat().st_mtime, tz_offset)
                if _year_matches(dt, target_year):
                    ws_res["sessions"] += 1
                    if dt:
                        ws_res["hours"][dt.hour] += 1
                        ws_res["days"].add(dt.strftime("%Y-%m-%d"))
    for uroot in _ide_user_roots(home, ("Windsurf",)):
        for cf in uroot.glob("workspaceStorage/*/chatSessions/*.json*"):
            if _scan_json_or_jsonl_file(cf, ws_res, tz_offset, target_year):
                ws_res["sessions"] += 1
    ws_res["detected"] = ws_res["sessions"] > 0 or sum(ws_res["tools"].values()) > 0
    out.append(("windsurf", "Windsurf", ws_res))

    # 2. Continue
    ct_res = _new_harness_res(False)
    ct_dir = home / ".continue" / "sessions"
    if ct_dir.exists():
        for cf in ct_dir.glob("*.json*"):
            if _scan_json_or_jsonl_file(cf, ct_res, tz_offset, target_year):
                ct_res["sessions"] += 1
    ct_res["detected"] = ct_res["sessions"] > 0 or sum(ct_res["tools"].values()) > 0
    out.append(("continue", "Continue", ct_res))

    # 3. Goose
    gs_res = _new_harness_res(False)
    for gd in (home / ".local" / "share" / "goose" / "sessions", home / ".config" / "goose" / "sessions"):
        if gd.exists():
            for gf in list(gd.glob("*.jsonl")) + list(gd.glob("*.json")):
                if _scan_json_or_jsonl_file(gf, gs_res, tz_offset, target_year):
                    gs_res["sessions"] += 1
            gdb = gd / "sessions.db"
            if gdb.exists() and gs_res["sessions"] == 0:
                try:
                    con = sqlite3.connect(f"file:{gdb}?immutable=1", uri=True)
                    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    if "sessions" in tables:
                        for row in con.execute("SELECT created_at FROM sessions"):
                            dt = _parse_any_dt(row[0], tz_offset)
                            if _year_matches(dt, target_year):
                                gs_res["sessions"] += 1
                                if dt:
                                    gs_res["hours"][dt.hour] += 1
                                    gs_res["days"].add(dt.strftime("%Y-%m-%d"))
                    con.close()
                except Exception:
                    pass
    gs_res["detected"] = gs_res["sessions"] > 0 or sum(gs_res["tools"].values()) > 0
    out.append(("goose", "Goose", gs_res))

    # 4. Aider (header timestamps + /run|/test counts only, never reading prose)
    ad_res = _new_harness_res(False)
    hist_md = home / ".aider.chat.history.md"
    if hist_md.exists():
        try:
            with hist_md.open("r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    if line.startswith("# aider chat started at "):
                        ts = line[len("# aider chat started at "):].strip().replace(" ", "T") + "Z"
                        dt = parse_iso_dt(ts, tz_offset)
                        if _year_matches(dt, target_year):
                            ad_res["sessions"] += 1
                            if dt:
                                ad_res["hours"][dt.hour] += 1
                                ad_res["days"].add(dt.strftime("%Y-%m-%d"))
                    elif line.startswith("/run ") or line.startswith("/test "):
                        _record_tool(ad_res, "Bash", {"command": line.split(" ", 1)[1]})
        except Exception:
            pass
    ad_desk = home / ".aider-desk"
    if ad_desk.exists():
        for sub in _SESSION_SUBDIRS:
            sd = ad_desk / sub
            if sd.exists():
                for fp in list(sd.rglob("*.jsonl"))[:300] + list(sd.rglob("*.json"))[:300]:
                    if _scan_json_or_jsonl_file(fp, ad_res, tz_offset, target_year):
                        ad_res["sessions"] += 1
    ad_res["detected"] = ad_res["sessions"] > 0 or sum(ad_res["tools"].values()) > 0
    out.append(("aider", "Aider", ad_res))
    return out


_GENERIC_AGENT_SPECS: list[tuple[str, str, tuple[str, ...]]] = [
    ("amp", "Amp", (".local/share/amp", ".amp")),
    ("crush", "Crush", (".local/share/crush", ".crush")),
    ("qwen", "Qwen Code", (".qwen",)),
    ("trae", "Trae", (".trae", ".trae-cn")),
    ("qoder", "Qoder", (".qoder", ".qoder-cn")),
    ("kiro", "Kiro", (".kiro",)),
    ("factory", "Factory Droid", (".factory",)),
    ("openhands", "OpenHands", (".openhands",)),
    ("vibe", "Mistral Vibe", (".vibe",)),
    ("hermes", "Hermes", (".hermes",)),
    ("junie", "Junie", (".junie",)),
    ("augment", "Augment", (".augment",)),
    ("iflow", "iFlow", (".iflow",)),
    ("grok", "Grok CLI", (".grok", ".grokbot")),
    ("lingma", "Lingma", (".lingma",)),
    ("codebuddy", "CodeBuddy", (".codebuddy",)),
    ("pi", "Pi", (".pi",)),
    ("mux", "Mux", (".mux",)),
    ("zencoder", "Zencoder", (".zencoder",)),
    ("rovodev", "Rovo Dev", (".rovodev",)),
    ("codeartsdoer", "CodeArts Doer", (".codeartsdoer",)),
    ("zed", "Zed AI", (".local/share/zed", "Library/Application Support/Zed")),
]


_NOISY_GENERIC_FILES = {
    "tool_definitions.json", "announcement_state.json", "resources_state.json",
    "prompt_context.json", "signals.json", "rewind_points.jsonl",
    "sandbox-events.jsonl", "updates.jsonl", "prompt_history.jsonl",
    "compaction_requests.jsonl", "compaction_checkpoints.jsonl", "meta.json",
    "summary.json", "usage.json", "plan.json", "plan_mode.json",
    "settings.json", "manifest.json", "config.json",
}


def collect_generic_harnesses(
    home: Path, tz_offset: float, target_year: int | None
) -> list[tuple[str, str, dict[str, Any]]]:
    """Scan session/transcript dirs (never skill-only or noisy state files) across 20+ agents."""
    results: list[tuple[str, str, dict[str, Any]]] = []
    for hid, display_name, rel_roots in _GENERIC_AGENT_SPECS:
        res = _new_harness_res(False)
        scanned_files = 0
        seen_session_keys: set[Path] = set()
        seen_subagent_keys: set[Path] = set()
        for rel in rel_roots:
            base = home / rel
            if not base.exists():
                continue
            for sub in _SESSION_SUBDIRS + ("conversations", "prompts"):
                cand = base / sub
                if not cand.exists():
                    continue
                for root, dirs, fnames in os.walk(cand, followlinks=False):
                    dirs[:] = [d for d in dirs if d not in _SKIP_WALK_DIRS]
                    for fn in fnames:
                        if scanned_files >= 400:
                            break
                        if fn in _NOISY_GENERIC_FILES or not (fn.endswith(".jsonl") or fn.endswith(".json")):
                            continue
                        fp = Path(root) / fn
                        scanned_files += 1
                        if _scan_json_or_jsonl_file(fp, res, tz_offset, target_year):
                            is_sub = "subagents" in fp.parts
                            # Group sibling files inside a UUID/session dir as one session
                            key = fp if fp.parent == cand else fp.parent
                            if is_sub:
                                seen_subagent_keys.add(fp.parent)
                            else:
                                seen_session_keys.add(key)
                    if scanned_files >= 400:
                        break
        res["sessions"] = len(seen_session_keys)
        res["subagents"] = len(seen_subagent_keys)
        res["detected"] = res["sessions"] > 0 or res["subagents"] > 0 or sum(res["tools"].values()) > 0
        if res["detected"]:
            results.append((hid, display_name, res))
    return results


def _count_unique_ecosystem_skills(home: Path, claude_count: int) -> int:
    """Count unique skill folders across agent skill roots without inflating duplicates."""
    skill_roots = [
        home / ".claude" / "skills",
        home / ".agents" / "skills",
        home / ".codex" / "skills",
        home / ".gemini" / "antigravity" / "skills",
        home / ".gemini" / "skills",
        home / ".kimi" / "skills",
        home / ".copilot" / "skills",
        home / ".local" / "share" / "opencode" / "skills",
    ]
    names: set[str] = set()
    for sr in skill_roots:
        if not sr.exists():
            continue
        try:
            for item in sr.iterdir():
                if item.is_dir() and not item.name.startswith("."):
                    names.add(item.name)
        except OSError:
            pass
    return max(claude_count, len(names))


def clamp_score(val: float) -> int:
    return max(0, min(100, int(round(val))))


def compute_radar_and_fallback(facts: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute 6 fixed universal viral radar scores (0..100) and punchy fallback persona."""
    totals = facts["totals"]
    inv = facts["inventory"]
    bdna = facts["bash_dna"]
    sessions_total = max(1, totals["sessions"])

    sub_ratio = totals["subagent_sessions"] / sessions_total
    multi_pct = totals["multi_tool_turn_pct"]
    bash_pct = totals["bash_share_pct"]
    night_pct = facts["night_owl_pct"]
    active_harnesses = sum(
        1 for h in facts["harnesses"] if h["detected"] and (h["sessions"] > 0 or h["tool_calls"] > 0 or h["subagents"] > 0)
    )
    detected_harnesses = active_harnesses or sum(1 for h in facts["harnesses"] if h["detected"])
    test_cmds = bdna.get("test_cmd_count", 0)
    total_gear = inv["skills_installed"] + inv["agents_installed"] + facts["distinct_tools"]

    # 6 fixed universal dimensions shared across all users (never tailored per user)
    night_owl = clamp_score(
        12 + 68 * min(1.0, night_pct / 60.0) + 20 * min(1.0, (1.0 if facts["peak_hour"] in (22, 23, 0, 1, 2, 3, 4, 5) and totals["tool_calls"] > 0 else 0.0))
    )
    boss_energy = clamp_score(
        15
        + (22 if inv["auto_or_bypass"] else 4)
        + 24 * min(1.0, math.log1p(sub_ratio) / math.log1p(8.0))
        + 20 * min(1.0, math.log1p(facts["loop_or_cron_count"]) / math.log1p(300))
        + 19 * min(1.0, multi_pct / 22.0)
    )
    gear_hoarder = clamp_score(
        12
        + 30 * min(1.0, detected_harnesses / 6.0)
        + 34 * min(1.0, math.log1p(total_gear) / math.log1p(450))
        + 24 * min(1.0, math.log1p(inv["plugins_unused"] + inv["plugins_total"]) / math.log1p(50))
    )
    trust_issues = clamp_score(
        18
        + 34 * min(1.0, math.log1p(test_cmds) / math.log1p(2500))
        + 26 * min(1.0, math.log1p(facts["verification_signals"]) / math.log1p(120))
        + 22 * min(1.0, math.log1p(bdna["rtk_proxy_count"]) / math.log1p(1500))
    )
    chaos_grit = clamp_score(
        16
        + 36 * min(1.0, bash_pct / 75.0)
        + 24 * min(1.0, bdna["piped_pct"] / 72.0)
        + 24 * min(1.0, math.log1p(bdna["heredoc_count"] + facts["distinct_projects"]) / math.log1p(15000))
    )
    ai_addict = clamp_score(
        10
        + 32 * min(1.0, totals["active_days"] / 180.0)
        + 30 * min(1.0, math.log1p(totals["tool_calls"]) / math.log1p(180000))
        + 28 * min(1.0, math.log1p(totals["sessions"] + totals["subagent_sessions"]) / math.log1p(4000))
    )

    axes = [
        {"key": "night_owl", "label": "夜猫纯度", "label_en": "Night Owl", "score": night_owl},
        {"key": "boss_energy", "label": "甩手掌柜", "label_en": "Boss Energy", "score": boss_energy},
        {"key": "gear_hoarder", "label": "装备狂魔", "label_en": "Gear Hoarder", "score": gear_hoarder},
        {"key": "trust_issues", "label": "疑心洁癖", "label_en": "Trust Issues", "score": trust_issues},
        {"key": "chaos_grit", "label": "硬核折腾", "label_en": "Chaos Grit", "score": chaos_grit},
        {"key": "ai_addict", "label": "含AI量", "label_en": "AI Addict", "score": ai_addict},
    ]

    # Keep fallback strictly neutral and factual: bespoke personality/archetype analysis
    # is delegated to the user's own AI agent via the prompt in SKILL.md.
    peak_hr = facts["peak_hour"]
    if totals["sessions"] == 0 and totals["tool_calls"] == 0:
        fallback = {
            "archetype_id": "wrapped-snapshot",
            "archetype_title": f"{facts['year']} AI 档案快照",
            "archetype_en": f"{facts['year']} AI Snapshot",
            "one_liner": "暂未扫描到本地 Agent 行动记录，在对话里唤醒 AI 即可解锁你的专属人格。",
            "one_liner_en": "No local agent logs found yet — run this skill with an AI agent once active.",
            "secondary_badges": ["待解锁记录", "100% 本地统计"],
            "secondary_badges_en": ["No Logs Yet", "100% Local"],
            "memes": [
                {
                    "tag": "0 场对话",
                    "tag_en": "0 Sessions",
                    "line": "本机暂未检测到该年份的 Agent 会话日志（可尝试加上 --all-time 参数）。",
                    "line_en": "No agent sessions recorded for this year yet (try --all-time).",
                },
                {
                    "tag": "0 次调用",
                    "tag_en": "0 Tool Calls",
                    "line": "等你在终端或编辑器里让 AI 跑几轮后，这里会自动填满你的真实战绩。",
                    "line_en": "Once an agent runs tools in your workspace, your real usage populates here.",
                },
                {
                    "tag": f"{inv['skills_installed']:,} 项本地配置",
                    "tag_en": f"{inv['skills_installed']:,} Local Skills",
                    "line": f"检测到 {detected_harnesses} 个本地 Harness、{inv['skills_installed']:,} 个已安装技能。",
                    "line_en": f"Detected {detected_harnesses} harnesses and {inv['skills_installed']:,} installed skills.",
                },
            ],
            "axis_notes": {
                "night_owl": "暂无深夜动作记录",
                "boss_energy": "暂无分身并发记录",
                "gear_hoarder": f"已装 {inv['skills_installed']:,} 项技能 · {inv['plugins_total']:,} 插件",
                "trust_issues": "暂无测试校验记录",
                "chaos_grit": "暂无终端调用记录",
                "ai_addict": "等待开启今年第 1 次 AI 对话",
            },
            "axis_notes_en": {
                "night_owl": "No late-night runs logged yet",
                "boss_energy": "No subagent bursts logged yet",
                "gear_hoarder": f"{inv['skills_installed']:,} skills · {inv['plugins_total']:,} plugins found",
                "trust_issues": "No verification runs logged yet",
                "chaos_grit": "No shell tool calls logged yet",
                "ai_addict": "Ready for your first AI session",
            },
        }
        return axes, fallback

    memes: list[dict[str, str]] = [
        {
            "tag": f"夜间 {night_pct:.0f}% · 峰值 {peak_hr:02d}:00",
            "tag_en": f"{night_pct:.0f}% Night · Peak {peak_hr:02d}:00",
            "line": f"全天最活跃在 {peak_hr:02d}:00，其中 {night_pct:.1f}% 的 AI 动作发生在 22:00–05:00。",
            "line_en": f"Activity peaks at {peak_hr:02d}:00, with {night_pct:.1f}% occurring between 22:00 and 05:00.",
        },
        {
            "tag": f"Grep={inv['grep_calls']:,} · Bash={totals['bash_calls']:,}",
            "tag_en": f"Grep={inv['grep_calls']:,} · Bash={totals['bash_calls']:,}",
            "line": f"原生 Grep 工具调用 {inv['grep_calls']:,} 次，终端 Bash 调用 {totals['bash_calls']:,} 次（占 {bash_pct:.1f}%）。",
            "line_en": f"Called built-in Grep {inv['grep_calls']:,} times vs {totals['bash_calls']:,} Bash calls ({bash_pct:.1f}%).",
        },
        {
            "tag": f"{inv['skills_installed']:,} 技能 · {inv['plugins_unused']:,} 未触发",
            "tag_en": f"{inv['skills_installed']:,} Skills · {inv['plugins_unused']:,} Unused",
            "line": f"本地安装 {inv['skills_installed']:,} 个技能与 {inv['plugins_total']:,} 个插件，其中 {inv['plugins_unused']:,} 个尚无使用记录。",
            "line_en": f"{inv['skills_installed']:,} skills & {inv['plugins_total']:,} plugins installed ({inv['plugins_unused']:,} untouched).",
        },
        {
            "tag": f"峰值并发 {totals['max_parallel_turn']}x · 活跃 {totals['active_days']:,} 天",
            "tag_en": f"{totals['max_parallel_turn']}x Peak · {totals['active_days']:,} Days",
            "line": f"跨 {facts['distinct_projects']:,} 个项目与 {detected_harnesses} 个 Agent，单轮最高并发 {totals['max_parallel_turn']} 次工具调用。",
            "line_en": f"Spanned {facts['distinct_projects']:,} workspaces and {detected_harnesses} harnesses, up to {totals['max_parallel_turn']}x parallel calls.",
        },
    ]

    fallback = {
        "archetype_id": "wrapped-snapshot",
        "archetype_title": f"{facts['year']} AI 使用实录",
        "archetype_en": f"{facts['year']} AI Dev Snapshot",
        "one_liner": f"跨 {detected_harnesses} 个 Agent 完成 {totals['sessions']:,} 场对话、{totals['tool_calls']:,} 次调用，最晚峰值停在 {peak_hr:02d}:00。",
        "one_liner_en": f"{totals['sessions']:,} sessions and {totals['tool_calls']:,} tool calls across {detected_harnesses} harnesses, peaking at {peak_hr:02d}:00.",
        "secondary_badges": [
            f"{detected_harnesses} 个本地 Agent",
            f"{totals['active_days']:,} 活跃天",
            f"峰值 {peak_hr:02d}:00",
        ],
        "secondary_badges_en": [
            f"{detected_harnesses} Harnesses",
            f"{totals['active_days']:,} Active Days",
            f"Peak {peak_hr:02d}:00",
        ],
        "memes": memes,
        "axis_notes": {
            "night_owl": f"{night_pct:.1f}% 夜间动作 · 峰值 {peak_hr:02d}:00",
            "boss_energy": f"{totals['sessions']:,} 轮对话带出 {totals['subagent_sessions']:,} 个子代理",
            "gear_hoarder": f"装了 {inv['skills_installed']:,} 技能与 {inv['plugins_total']:,} 插件",
            "trust_issues": f"{test_cmds:,} 次测试指令 · {bdna['rtk_proxy_count']:,} 次原始查看",
            "chaos_grit": f"{bash_pct:.1f}% 走终端 · 管道率 {bdna['piped_pct']:.1f}%",
            "ai_addict": f"全年活跃 {totals['active_days']:,} 天 · 总计 {totals['tool_calls']:,} 次",
        },
        "axis_notes_en": {
            "night_owl": f"{night_pct:.1f}% after-hours · peak {peak_hr:02d}:00",
            "boss_energy": f"{totals['sessions']:,} sessions · {totals['subagent_sessions']:,} subagents",
            "gear_hoarder": f"{inv['skills_installed']:,} skills · {inv['plugins_total']:,} plugins",
            "trust_issues": f"{test_cmds:,} test runs · {bdna['rtk_proxy_count']:,} raw checks",
            "chaos_grit": f"{bash_pct:.1f}% raw shell · {bdna['piped_pct']:.1f}% piped",
            "ai_addict": f"{totals['active_days']:,} active days · {totals['tool_calls']:,} calls",
        },
    }
    return axes, fallback


def collect_all(home: Path, tz_offset: float | None = None, year: int | None = None, all_time: bool = False) -> dict[str, Any]:
    """Run all harness collectors and assemble sanitized facts JSON."""
    if tz_offset is None:
        tz_offset = detect_host_tz_offset()
    if year is None:
        year = datetime.datetime.now().year
    filter_year = None if all_time else year

    home_str = str(home)
    warnings: list[str] = []
    harness_parts: list[tuple[str, str, dict[str, Any], bool]] = [
        ("claude", "Claude Code / Desktop", collect_claude(home, tz_offset, filter_year, warnings), True),
        ("codex", "OpenAI Codex", collect_codex(home, tz_offset, filter_year, warnings), True),
        ("antigravity", "Antigravity", collect_antigravity(home, tz_offset, filter_year, warnings), True),
        ("kimi", "Kimi CLI", collect_kimi(home, tz_offset, filter_year, warnings), True),
        ("openclaw", "OpenClaw", collect_openclaw(home, tz_offset, filter_year, warnings), True),
        ("autoclaw", "AutoClaw", collect_autoclaw(home, tz_offset, filter_year, warnings), False),
        ("cursor", "Cursor", collect_cursor(home, tz_offset, filter_year, warnings), True),
        ("copilot", "GitHub Copilot", collect_copilot(home, tz_offset, filter_year, warnings), False),
        ("gemini-cli", "Gemini CLI", collect_gemini_cli(home, tz_offset, filter_year, warnings), False),
        ("cline", "Cline", collect_ide_extension_agent(home, tz_offset, filter_year, warnings, ("saoudrizwan.claude-dev",), (".cline",)), False),
        ("roo-code", "Roo Code", collect_ide_extension_agent(home, tz_offset, filter_year, warnings, ("rooveterinaryinc.roo-cline",), (".roo",)), False),
        ("kilo-code", "Kilo Code", collect_ide_extension_agent(home, tz_offset, filter_year, warnings, ("kilocode.kilo-code",), (".kilocode",)), False),
        ("opencode", "OpenCode", collect_opencode(home, tz_offset, filter_year, warnings), False),
    ]
    for hid, dname, hpart in collect_windsurf_continue_goose_aider(home, tz_offset, filter_year, warnings):
        harness_parts.append((hid, dname, hpart, False))
    for hid, dname, hpart in collect_generic_harnesses(home, tz_offset, filter_year):
        harness_parts.append((hid, dname, hpart, False))

    claude = harness_parts[0][2]
    codex = harness_parts[1][2]

    total_tools: Counter[str] = Counter()
    total_models: Counter[str] = Counter()
    total_verbs: Counter[str] = Counter()
    total_bflags: Counter[str] = Counter()
    total_hours: Counter[int] = Counter()
    total_days: set[str] = set()
    total_projects: set[str] = set()
    turn_sizes: list[int] = []

    for _, _, part, _ in harness_parts:
        total_tools.update(part.get("tools", {}))
        total_models.update(part.get("models", {}))
        total_verbs.update(part.get("verbs", {}))
        total_bflags.update(part.get("bflags", {}))
        total_hours.update(part.get("hours", {}))
        total_days.update(part.get("days", set()))
        total_projects.update(part.get("projects", set()))
        turn_sizes.extend(part.get("turn_sizes", []))

    all_tool_calls = sum(total_tools.values())
    bash_calls = total_tools.get("Bash", 0) + total_tools.get("bash", 0)
    bash_share_pct = round(bash_calls * 100.0 / all_tool_calls, 1) if all_tool_calls else 0.0

    hours_list = [total_hours.get(h, 0) for h in range(24)]
    hours_sum = sum(hours_list)
    night_sum = sum(hours_list[h] for h in (22, 23, 0, 1, 2, 3, 4, 5))
    night_owl_pct = round(night_sum * 100.0 / hours_sum, 1) if hours_sum else 0.0
    peak_hour = max(range(24), key=lambda h: hours_list[h]) if hours_sum else 0

    multi_turns = sum(1 for x in turn_sizes if x > 1)
    multi_pct = round(multi_turns * 100.0 / len(turn_sizes), 1) if turn_sizes else 0.0
    max_par = max(turn_sizes) if turn_sizes else (1 if all_tool_calls else 0)

    b_total = max(1, total_bflags.get("total", 0))
    chained_pct = round(total_bflags.get("chained", 0) * 100.0 / b_total, 1) if total_bflags.get("total") else 0.0
    piped_pct = round(total_bflags.get("piped", 0) * 100.0 / b_total, 1) if total_bflags.get("total") else 0.0

    harnesses = [
        {
            "id": hid,
            "name": dname,
            "detected": bool(part.get("detected")),
            "sessions": int(part.get("sessions", 0)),
            "subagents": int(part.get("subagents", 0)),
            "tool_calls": sum(part.get("tools", {}).values()),
        }
        for hid, dname, part, always_keep in harness_parts
        if always_keep or part.get("detected")
    ]

    su = claude["skill_usage"]
    verif_signals = (
        su.get("superpowers:verification-before-completion", 0)
        + su.get("superpowers:test-driven-development", 0)
        + su.get("superpowers:systematic-debugging", 0)
        + su.get("delivery-readiness-audit", 0)
        + su.get("code-review", 0)
    )
    loop_count = su.get("loop", 0) + total_tools.get("ScheduleWakeup", 0) + total_tools.get("CronCreate", 0)

    inv = claude["inventory"]
    inv["skills_installed"] = _count_unique_ecosystem_skills(home, inv["skills_installed"])
    inv["auto_or_bypass"] = any(part.get("auto_or_bypass") for _, _, part, _ in harness_parts)
    inv["grep_calls"] = total_tools.get("Grep", 0)
    inv["glob_calls"] = total_tools.get("Glob", 0)

    total_sessions = sum(h["sessions"] for h in harnesses)
    total_subagents = sum(h["subagents"] for h in harnesses)

    now_local = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=tz_offset)))
    facts: dict[str, Any] = {
        "schema_version": "1.0",
        "year": year,
        "all_time": all_time,
        "generated_at": now_local.isoformat(timespec="seconds"),
        "timezone_label": f"UTC{tz_offset:+g}",
        "totals": {
            "sessions": total_sessions,
            "subagent_sessions": total_subagents,
            "tool_calls": all_tool_calls,
            "bash_calls": bash_calls,
            "bash_share_pct": bash_share_pct,
            "active_days": len(total_days),
            "max_parallel_turn": max_par,
            "multi_tool_turn_pct": multi_pct,
        },
        "harnesses": harnesses,
        "hours": hours_list,
        "night_owl_pct": night_owl_pct,
        "peak_hour": peak_hour,
        "top_tools": [
            {
                "name": sanitize_text(k, home_str),
                "count": v,
                "pct": round(v * 100.0 / all_tool_calls, 1) if all_tool_calls else 0.0,
            }
            for k, v in total_tools.most_common(12)
        ],
        "top_models": [
            {"name": sanitize_text(k, home_str), "count": v}
            for k, v in total_models.most_common(8)
        ],
        "bash_dna": {
            "total_bash_calls": total_bflags.get("total", 0),
            "chained_pct": chained_pct,
            "piped_pct": piped_pct,
            "heredoc_count": total_bflags.get("heredoc", 0),
            "rtk_proxy_count": total_bflags.get("rtk_proxy", 0),
            "git_quotepath_count": total_bflags.get("git_quotepath", 0),
            "worktree_cmd_count": total_bflags.get("worktree_cmd", 0),
            "test_cmd_count": total_bflags.get("test_cmd", 0),
            "top_commands": [
                {"name": sanitize_text(k, home_str), "count": v}
                for k, v in total_verbs.most_common(12)
            ],
        },
        "inventory": inv,
        "distinct_projects": len(total_projects),
        "distinct_tools": len(total_tools),
        "verification_signals": verif_signals,
        "loop_or_cron_count": loop_count,
        "warnings": warnings[:10],
    }

    axes, fallback = compute_radar_and_fallback(facts)
    facts["radar_axes"] = axes
    facts["fallback_persona"] = fallback

    raw_json = json.dumps(facts, ensure_ascii=False, indent=2)
    scrubbed_json = sanitize_text(raw_json, home_str)
    return json.loads(scrubbed_json)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect multi-harness AI developer stats into sanitized JSON.")
    parser.add_argument("--home", default=str(Path.home()), help="User home directory to scan")
    parser.add_argument("--output", default="/tmp/ai_wrapped_facts.json", help="Output JSON path")
    parser.add_argument("--tz-offset", type=float, default=None, help="Timezone offset in hours (default: host local)")
    parser.add_argument("--year", type=int, default=datetime.datetime.now().year, help="Target summary year")
    parser.add_argument("--all-time", action="store_true", help="Aggregate all years instead of filtering to --year")
    args = parser.parse_args()

    facts = collect_all(Path(args.home).resolve(), args.tz_offset, args.year, args.all_time)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(facts, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[collect] wrote {out} ({facts['totals']['tool_calls']} tool calls across {facts['totals']['sessions']} sessions)")


if __name__ == "__main__":
    main()
