#!/usr/bin/env python3
"""Render AI Developer Wrapped HTML and serve over localhost."""

from __future__ import annotations

import argparse
import http.server
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TEMPLATE = ROOT / "templates" / "wrapped.html"
PID_FILE = Path(tempfile.gettempdir()) / "ai_wrapped_server.pid"

STR_FIELDS = (
    "archetype_id",
    "archetype_title",
    "archetype_en",
    "one_liner",
    "one_liner_en",
    "display_name",
    "verdict_level",
    "verdict_level_en",
    "verdict_body",
    "verdict_body_en",
)


def _clean_str_list(val: Any) -> list[str] | None:
    if not isinstance(val, list):
        return None
    cleaned = [str(x).strip() for x in val if isinstance(x, str) and x.strip()]
    return cleaned if cleaned else None


def _clean_memes(val: Any) -> list[dict[str, str]] | None:
    if not isinstance(val, list):
        return None
    out: list[dict[str, str]] = []
    for item in val:
        if not isinstance(item, dict):
            continue
        tag = item.get("tag")
        line = item.get("line")
        if isinstance(tag, str) and tag.strip() and isinstance(line, str) and line.strip():
            entry: dict[str, str] = {"tag": tag.strip(), "line": line.strip()}
            tag_en = item.get("tag_en")
            line_en = item.get("line_en")
            entry["tag_en"] = tag_en.strip() if isinstance(tag_en, str) and tag_en.strip() else entry["tag"]
            entry["line_en"] = line_en.strip() if isinstance(line_en, str) and line_en.strip() else entry["line"]
            out.append(entry)
    return out if out else None


def validate_and_merge_persona(facts: dict[str, Any], persona_path: Path | None) -> dict[str, Any]:
    """Load AI-generated persona JSON with strict type validation and safe fallback."""
    fallback = dict(facts.get("fallback_persona") or {})
    if not persona_path or not persona_path.exists():
        return fallback

    try:
        loaded = json.loads(persona_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return fallback
    except Exception:
        return fallback

    merged = dict(fallback)
    for k in STR_FIELDS:
        val = loaded.get(k)
        if isinstance(val, str) and val.strip():
            merged[k] = val.strip()

    # Prevent mixing newly authored ZH copy with stale fallback EN copy
    for zh_k, en_k in (("one_liner", "one_liner_en"), ("verdict_level", "verdict_level_en"), ("verdict_body", "verdict_body_en")):
        if isinstance(loaded.get(zh_k), str) and loaded[zh_k].strip():
            if not (isinstance(loaded.get(en_k), str) and loaded[en_k].strip()):
                merged[en_k] = merged[zh_k]

    badges = _clean_str_list(loaded.get("secondary_badges"))
    if badges:
        merged["secondary_badges"] = badges
        badges_en = _clean_str_list(loaded.get("secondary_badges_en"))
        merged["secondary_badges_en"] = badges_en if badges_en else badges
    else:
        badges_en = _clean_str_list(loaded.get("secondary_badges_en"))
        if badges_en:
            merged["secondary_badges_en"] = badges_en

    memes = _clean_memes(loaded.get("memes"))
    if memes:
        merged["memes"] = memes

    has_custom_notes = False
    valid_axis_keys = set(fallback.get("axis_notes", {}).keys())
    for note_key in ("axis_notes", "axis_notes_en"):
        fb_notes = dict(fallback.get(note_key) or {})
        raw_notes = loaded.get(note_key)
        if isinstance(raw_notes, dict):
            cleaned_notes = {
                str(k): str(v).strip()
                for k, v in raw_notes.items()
                if (not valid_axis_keys or str(k) in valid_axis_keys) and isinstance(v, str) and v.strip()
            }
            if cleaned_notes:
                fb_notes.update(cleaned_notes)
                if note_key == "axis_notes":
                    has_custom_notes = True
        merged[note_key] = fb_notes

    if has_custom_notes and not (isinstance(loaded.get("axis_notes_en"), dict) and any(
        isinstance(v, str) and v.strip()
        for k, v in loaded["axis_notes_en"].items()
        if not valid_axis_keys or str(k) in valid_axis_keys
    )):
        merged["axis_notes_en"] = merged["axis_notes"]
    return merged


def safe_inline_json(obj: Any) -> str:
    """Serialize JSON safely (RFC 8259 valid) for embedding inside <script>."""
    raw = json.dumps(obj, ensure_ascii=False)
    # Escaping '<' as '\\u003c' neutralizes '</script>' and '<!--' with 100% valid JSON
    return raw.replace("<", "\\u003c").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def render_html(
    facts: dict[str, Any],
    persona: dict[str, Any],
    default_lang: str = "auto",
    template_path: Path = DEFAULT_TEMPLATE,
) -> str:
    """Inject sanitized payload into HTML template."""
    tpl = template_path.read_text(encoding="utf-8")
    payload = {"facts": facts, "persona": persona, "default_lang": default_lang}
    return tpl.replace("__WRAPPED_JSON__", safe_inline_json(payload))


def make_single_page_handler(html_bytes: bytes) -> type[http.server.BaseHTTPRequestHandler]:
    """Serve only the rendered HTML page (never expose directory listings)."""

    class SinglePageHandler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path in ("/", "/index.html"):
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html_bytes)
            elif path == "/favicon.ico":
                self.send_response(204)
                self.end_headers()
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    return SinglePageHandler


class ReusableThreadingHTTPServer(http.server.ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_http_server(html_source: Path | str, port: int = 0) -> tuple[ReusableThreadingHTTPServer, int]:
    """Start localhost single-page HTTP server on 127.0.0.1 and return (server, bound_port)."""
    if isinstance(html_source, Path):
        target = html_source / "index.html" if html_source.is_dir() else html_source
        html_bytes = target.read_bytes()
    else:
        html_bytes = html_source.encode("utf-8")
    handler = make_single_page_handler(html_bytes)
    server = ReusableThreadingHTTPServer(("127.0.0.1", port), handler)
    bound_port = int(server.server_address[1])
    return server, bound_port


def open_browser(url: str) -> None:
    """Open localhost URL in the OS default browser reliably."""
    system = platform.system()
    try:
        if system == "Darwin" and shutil.which("open"):
            subprocess.Popen(["open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        if system == "Linux" and shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
    except Exception:
        pass
    webbrowser.open(url)


def _is_our_render_process(pid: int) -> bool:
    """Verify PID actually belongs to render.py before signaling (guards against PID reuse)."""
    try:
        ps_bin = shutil.which("ps") or "/bin/ps"
        proc = subprocess.run([ps_bin, "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=2)
        return proc.returncode == 0 and "render.py" in proc.stdout
    except Exception:
        return False


def stop_previous_server() -> None:
    """Safely terminate an older background wrapped server if verified."""
    if not PID_FILE.exists():
        return
    try:
        raw = PID_FILE.read_text(encoding="utf-8").strip()
        pid = int(json.loads(raw)["pid"]) if raw.startswith("{") else int(raw)
        if pid > 0 and pid != os.getpid() and _is_our_render_process(pid):
            os.kill(pid, 15)
            for _ in range(20):
                try:
                    os.kill(pid, 0)
                    time.sleep(0.05)
                except OSError:
                    break
    except Exception:
        pass
    finally:
        try:
            PID_FILE.unlink(missing_ok=True)
        except Exception:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Render and serve AI Developer Wrapped.")
    parser.add_argument("--facts", default="/tmp/ai_wrapped_facts.json", help="Path to sanitized facts.json (default: /tmp/ai_wrapped_facts.json)")
    parser.add_argument("--persona", default="", help="Optional path to AI-authored persona.json")
    parser.add_argument("--out", default="/tmp/ai_wrapped_site/index.html", help="Output HTML path")
    parser.add_argument("--lang", default="auto", choices=["auto", "zh", "en"], help="Initial UI language")
    parser.add_argument("--serve", action="store_true", help="Serve over 127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="Port to bind (0 = ephemeral free port)")
    parser.add_argument("--open", action="store_true", help="Open browser automatically")
    parser.add_argument("--daemon", action="store_true", help="Detach background server and exit immediately")
    parser.add_argument("--_daemon-child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    facts_path = Path(args.facts).resolve()
    if not facts_path.exists():
        parser.error(f"Facts file not found: {facts_path}. Run scripts/collect.py first.")
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    persona_path = Path(args.persona).resolve() if args.persona else None
    persona = validate_and_merge_persona(facts, persona_path)

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = render_html(facts, persona, default_lang=args.lang)
    out_path.write_text(html, encoding="utf-8")
    if not args._daemon_child:
        print(f"[render] wrote {out_path}")

    if not args.serve:
        return

    if args.daemon and not args._daemon_child:
        stop_previous_server()
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--facts",
            str(facts_path),
            "--out",
            str(out_path),
            "--lang",
            args.lang,
            "--serve",
            "--port",
            str(args.port),
            "--_daemon-child",
        ]
        if persona_path:
            cmd.extend(["--persona", str(persona_path)])

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
            text=True,
        )
        url = ""
        if proc.stdout:
            for line in proc.stdout:
                line = line.strip()
                if line.startswith("URL="):
                    url = line[4:]
                    break
        if url:
            print(f"[render] serving in background: {url}")
            if args.open:
                open_browser(url)
            return
        err_msg = proc.stderr.read().strip() if proc.stderr else ""
        print(f"[render] ERROR: failed to start background server ({err_msg})", file=sys.stderr)
        sys.exit(1)

    server, bound_port = start_http_server(html, args.port)
    url = f"http://127.0.0.1:{bound_port}/"
    if args._daemon_child:
        PID_FILE.write_text(json.dumps({"pid": os.getpid(), "port": bound_port}), encoding="utf-8")
        print(f"URL={url}", flush=True)
        try:
            sys.stdout.close()
            sys.stderr.close()
        except Exception:
            pass
    else:
        print(f"[render] serving at {url}", flush=True)
        if args.open:
            open_browser(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if args._daemon_child:
            try:
                PID_FILE.unlink(missing_ok=True)
            except Exception:
                pass


if __name__ == "__main__":
    main()
