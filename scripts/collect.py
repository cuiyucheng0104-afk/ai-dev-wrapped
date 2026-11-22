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


def collect_openclaw(home: Path, tz_offset: float, target_year: int | None, warnings: list[str]) -> dict[str, Any]:
    """Collect OpenClaw agent transcripts."""
    agents_dir = home / ".openclaw" / "agents"
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
                    dt = parse_iso_dt(d.get("timestamp", ""), tz_offset)
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
                            for blk in msg.get("content") or []:
                                if isinstance(blk, dict) and blk.get("type") == "toolCall":
                                    name = str(blk.get("name") or "tool")
                                    if name in ("exec", "bash", "shell"):
                                        res["tools"]["Bash"] += 1
                                        args = blk.get("arguments") or {}
                                        if isinstance(args, dict) and isinstance(args.get("command"), str):
                                            analyze_bash_command(args["command"], res["verbs"], res["bflags"])
                                    else:
                                        res["tools"][name] += 1
        except Exception as e:
            warnings.append(f"openclaw session read failed: {type(e).__name__}")
        if sess_active:
            res["sessions"] += 1
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


def clamp_score(val: float) -> int:
    return max(0, min(100, int(round(val))))


def compute_radar_and_fallback(facts: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compute balanced 6-axis scores (0..100) and deterministic fallback persona."""
    totals = facts["totals"]
    inv = facts["inventory"]
    bdna = facts["bash_dna"]
    sessions_total = max(1, totals["sessions"])

    sub_ratio = totals["subagent_sessions"] / sessions_total
    multi_pct = totals["multi_tool_turn_pct"]
    bash_pct = totals["bash_share_pct"]
    night_pct = facts["night_owl_pct"]
    detected_harnesses = sum(1 for h in facts["harnesses"] if h["detected"])
    test_cmds = bdna.get("test_cmd_count", 0)

    orchestration = clamp_score(
        20
        + 26 * min(1.0, math.log1p(totals["subagent_sessions"]) / math.log1p(2500))
        + 24 * min(1.0, math.log1p(sub_ratio) / math.log1p(8.0))
        + 15 * min(1.0, multi_pct / 22.0)
        + 15 * min(1.0, totals["max_parallel_turn"] / 18.0)
    )
    shell_craft = clamp_score(
        18
        + 42 * min(1.0, bash_pct / 75.0)
        + 22 * min(1.0, bdna["piped_pct"] / 72.0)
        + 16 * min(1.0, math.log1p(bdna["heredoc_count"]) / math.log1p(15000))
    )
    domain_span = clamp_score(
        18
        + 38 * min(1.0, detected_harnesses / 6.0)
        + 24 * min(1.0, math.log1p(facts["distinct_projects"]) / math.log1p(300))
        + 18 * min(1.0, math.log1p(facts["distinct_tools"]) / math.log1p(180))
    )
    verification = clamp_score(
        20
        + 44 * min(1.0, math.log1p(test_cmds) / math.log1p(2500))
        + 32 * min(1.0, math.log1p(facts["verification_signals"]) / math.log1p(120))
    )
    night_ops = clamp_score(
        18
        + 60 * min(1.0, night_pct / 60.0)
        + 20 * min(1.0, totals["active_days"] / 180.0)
    )
    autonomy = clamp_score(
        22
        + (34 if inv["auto_or_bypass"] else 5)
        + 22 * min(1.0, math.log1p(facts["loop_or_cron_count"]) / math.log1p(400))
        + 20 * min(1.0, math.log1p(totals["tool_calls"]) / math.log1p(180000))
    )

    axes = [
        {"key": "orchestration", "label": "编排杠杆", "label_en": "Orchestration", "score": orchestration},
        {"key": "shell_craft", "label": "终端功底", "label_en": "Shell Craft", "score": shell_craft},
        {"key": "domain_span", "label": "跨界广度", "label_en": "Domain Span", "score": domain_span},
        {"key": "verification", "label": "工程洁癖", "label_en": "Verification", "score": verification},
        {"key": "night_ops", "label": "夜战耐力", "label_en": "Night Ops", "score": night_ops},
        {"key": "autonomy", "label": "放权程度", "label_en": "Autonomy", "score": autonomy},
    ]

    if night_pct >= 45 and totals["subagent_sessions"] >= 50:
        arch = (
            "nightshift-orchestrator",
            "深夜蜂群总工",
            "Nightshift Swarm Architect",
            f"凌晨 {facts['peak_hour']:02d}:00 才是你的早高峰，一个主会话能裂变出成百上千个子代理。",
            f"{facts['peak_hour']:02d}:00 is your morning rush hour, spinning one session into swarms of subagents.",
        )
    elif totals["subagent_sessions"] > totals["sessions"] * 2:
        arch = (
            "swarm-commander",
            "蜂群指挥官",
            "Swarm Commander",
            "比起亲自一行行敲代码，你更习惯同时拉起多个工作树与子代理流水线。",
            "Why edit line by line when you can orchestrate parallel worktrees and agent pipelines.",
        )
    elif bash_pct >= 62:
        arch = (
            "shell-alchemist",
            "终端炼金术士",
            "Shell Alchemist",
            f"{bash_pct:.1f}% 的工具调用直奔终端，万物皆可一行管道 + heredoc 解决。",
            f"{bash_pct:.1f}% of all tool calls go straight to Bash — pipelines and heredocs rule everything.",
        )
    elif detected_harnesses >= 4:
        arch = (
            "fullstack-maverick",
            "跨界特种兵",
            "Full-Stack Maverick",
            f"同时驾驭 {detected_harnesses} 套 AI Harness 与跨软件工具链，哪把顺手用哪把。",
            f"Wielding {detected_harnesses} AI harnesses side by side — whichever fits the mission wins.",
        )
    elif verification >= 80:
        arch = (
            "verification-purist",
            "洁癖守门人",
            "Verification Purist",
            "不拿到实测输出和只读复核结论，绝不轻易宣称完成。",
            "Nothing ships without live verification and an independent read-only audit.",
        )
    elif inv["auto_or_bypass"]:
        arch = (
            "full-auto-speedrunner",
            "全自动狂飙派",
            "Full-Auto Speedrunner",
            "权限全开 + 循环拉满，把确认弹窗的时间全换成吞吐量。",
            "Full-auto permissions with continuous loops — zero clicks wasted on confirmations.",
        )
    else:
        arch = (
            "minimalist-craftsman",
            "克制极简派",
            "Minimalist Craftsman",
            "工具不多，但每次 Read/Edit 都切在要害上。",
            "Fewer tools, sharper cuts — every Read and Edit lands cleanly.",
        )

    badges = []
    badges_en = []
    if night_pct >= 40:
        badges.append("深夜突击型")
        badges_en.append("Night-Shift Raider")
    if bash_pct >= 55:
        badges.append("重度管道党")
        badges_en.append("Pipeline Maximalist")
    if inv["plugins_unused"] >= 5 or inv["skills_installed"] >= 50:
        badges.append("赛博松鼠党")
        badges_en.append("Skill Hoarder")
    if detected_harnesses >= 3:
        badges.append("多刀流玩家")
        badges_en.append("Multi-Harness")
    if not badges:
        badges.append("稳健迭代派")
        badges_en.append("Steady Shipper")

    memes: list[dict[str, str]] = []
    if totals["bash_calls"] >= 100 and (inv["grep_calls"] <= 5 or inv["grep_calls"] * 200 < totals["bash_calls"]):
        memes.append({
            "tag": f"Grep={inv['grep_calls']} · Bash={totals['bash_calls']:,}",
            "tag_en": f"Grep={inv['grep_calls']} · Bash={totals['bash_calls']:,}",
            "line": "原生 Grep 形同虚设，管道 grep + head + sed 才是我的主力引擎。",
            "line_en": "Hardly touched Grep — grep | head | sed is my native runtime.",
        })
    if night_pct >= 40:
        memes.append({
            "tag": f"峰值 {facts['peak_hour']:02d}:00",
            "tag_en": f"Peak {facts['peak_hour']:02d}:00",
            "line": f"{night_pct:.0f}% 的代码与指令诞生在 22:00–05:00，月亮不睡我不睡。",
            "line_en": f"{night_pct:.0f}% of prompts fired between 22:00 and 05:00 — sleep is optional.",
        })
    if bdna["rtk_proxy_count"] >= 10:
        cnt = bdna["rtk_proxy_count"]
        memes.append({
            "tag": f"{cnt:,} 次 rtk proxy",
            "tag_en": f"{cnt:,}x rtk proxy",
            "line": "亲手装上输出压缩钩子省 Token，遇到看不清时又亲自喊撤回。",
            "line_en": f"Installed a token compressor hook, then bypassed it {cnt:,} times for full output.",
        })
    if inv["plugins_unused"] >= 5:
        memes.append({
            "tag": f"{inv['skills_installed']} 个技能库存",
            "tag_en": f"{inv['skills_installed']} Skills Installed",
            "line": f"{inv['plugins_total']} 个插件里有 {inv['plugins_unused']} 个还是零次点击，先收藏就是会了。",
            "line_en": f"{inv['plugins_unused']} of {inv['plugins_total']} plugins sit at 0 runs — installing counts as learning.",
        })

    # Distinct fallback fillers so even an empty or daytime profile never duplicates cards
    filler_pool = [
        {
            "tag": f"{totals['sessions']:,} 次协作回合",
            "tag_en": f"{totals['sessions']:,} Sessions",
            "line": f"累计和本机 {detected_harnesses} 套 Agent 协同完成 {totals['tool_calls']:,} 次动作。",
            "line_en": f"Executed {totals['tool_calls']:,} tool calls across {detected_harnesses} local AI harnesses.",
        },
        {
            "tag": f"{totals['active_days']:,} 活跃天",
            "tag_en": f"{totals['active_days']:,} Active Days",
            "line": f"跨过 {facts['distinct_projects']:,} 个工作区，白天写需求，夜里收工单。",
            "line_en": f"Shipped across {facts['distinct_projects']:,} workspaces with {night_pct:.0f}% night activity.",
        },
        {
            "tag": f"并发峰值 {totals['max_parallel_turn']}x",
            "tag_en": f"Peak {totals['max_parallel_turn']}x Parallel",
            "line": f"多工具并行率 {totals['multi_tool_turn_pct']:.1f}%，能一轮解决的事绝不拆两轮。",
            "line_en": f"{totals['multi_tool_turn_pct']:.1f}% multi-tool turns — why wait two turns when one works.",
        },
    ]
    for card in filler_pool:
        if len(memes) >= 3:
            break
        memes.append(card)

    fallback = {
        "archetype_id": arch[0],
        "archetype_title": arch[1],
        "archetype_en": arch[2],
        "one_liner": arch[3],
        "one_liner_en": arch[4],
        "secondary_badges": badges[:3],
        "secondary_badges_en": badges_en[:3],
        "memes": memes[:4],
        "axis_notes": {
            "orchestration": f"主会话 {totals['sessions']:,} / 子代理 {totals['subagent_sessions']:,}",
            "shell_craft": f"Bash 占比 {bash_pct:.1f}%，管道率 {bdna['piped_pct']:.1f}%",
            "domain_span": f"覆盖 {detected_harnesses} 套 Agent、{facts['distinct_projects']} 个工作区",
            "verification": f"测试与验证命令 {test_cmds:,} 次",
            "night_ops": f"夜间活跃 {night_pct:.1f}%，峰值 {facts['peak_hour']:02d}:00",
            "autonomy": "已启用 Auto/Bypass 自动模式" if inv["auto_or_bypass"] else "审慎确认授权模式",
        },
        "axis_notes_en": {
            "orchestration": f"{totals['sessions']:,} main / {totals['subagent_sessions']:,} subagents",
            "shell_craft": f"{bash_pct:.1f}% Bash · {bdna['piped_pct']:.1f}% piped",
            "domain_span": f"{detected_harnesses} harnesses · {facts['distinct_projects']} workspaces",
            "verification": f"{test_cmds:,} test/verify commands",
            "night_ops": f"{night_pct:.1f}% night activity · peak {facts['peak_hour']:02d}:00",
            "autonomy": "Auto / Bypass enabled" if inv["auto_or_bypass"] else "Prompt-gated approvals",
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
    claude = collect_claude(home, tz_offset, filter_year, warnings)
    codex = collect_codex(home, tz_offset, filter_year, warnings)
    antigravity = collect_antigravity(home, tz_offset, filter_year, warnings)
    kimi = collect_kimi(home, tz_offset, filter_year, warnings)
    openclaw = collect_openclaw(home, tz_offset, filter_year, warnings)
    cursor = collect_cursor(home, tz_offset, filter_year, warnings)

    total_tools: Counter[str] = Counter()
    total_models: Counter[str] = Counter()
    total_verbs: Counter[str] = Counter()
    total_bflags: Counter[str] = Counter()
    total_hours: Counter[int] = Counter()
    total_days: set[str] = set()
    total_projects: set[str] = set()
    turn_sizes: list[int] = []

    for part in (claude, codex, antigravity, kimi, openclaw, cursor):
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
            "id": "claude",
            "name": "Claude Code / Desktop",
            "detected": claude["detected"],
            "sessions": claude["sessions"],
            "subagents": claude["subagents"],
            "tool_calls": sum(claude["tools"].values()),
        },
        {
            "id": "codex",
            "name": "OpenAI Codex",
            "detected": codex["detected"],
            "sessions": codex["sessions"],
            "subagents": codex["subagents"],
            "tool_calls": sum(codex["tools"].values()),
        },
        {
            "id": "antigravity",
            "name": "Antigravity",
            "detected": antigravity["detected"],
            "sessions": antigravity["sessions"],
            "subagents": 0,
            "tool_calls": sum(antigravity["tools"].values()),
        },
        {
            "id": "kimi",
            "name": "Kimi CLI",
            "detected": kimi["detected"],
            "sessions": kimi["sessions"],
            "subagents": 0,
            "tool_calls": sum(kimi["tools"].values()),
        },
        {
            "id": "openclaw",
            "name": "OpenClaw",
            "detected": openclaw["detected"],
            "sessions": openclaw["sessions"],
            "subagents": 0,
            "tool_calls": sum(openclaw["tools"].values()),
        },
        {
            "id": "cursor",
            "name": "Cursor",
            "detected": cursor["detected"],
            "sessions": cursor["sessions"],
            "subagents": 0,
            "tool_calls": sum(cursor["tools"].values()),
        },
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
    inv["auto_or_bypass"] = claude["auto_or_bypass"] or codex["auto_or_bypass"]
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
