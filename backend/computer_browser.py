import html
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv

from .app_paths import bundle_dir, data_dir, db_path, exe_dir

load_dotenv()


HIGH_IMPACT_PATTERNS = [
    "apagar",
    "aprovar",
    "cancelar",
    "comprar",
    "confirmar",
    "deletar",
    "enviar",
    "excluir",
    "pagar",
    "pix",
    "postar",
    "publicar",
    "submit",
    "transferir",
    "assinar",
    "delete",
    "buy",
    "checkout",
    "purchase",
    "send",
    "pay",
    "publish",
]


class _ReadableHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self._skip = False
        self._skip_stack = []
        self.text_parts = []
        self.links = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs or [])
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_stack.append(tag)
            self._skip = True
        if tag == "title":
            self._in_title = True
        if tag == "a" and attrs.get("href"):
            label = ""
            self.links.append({"href": attrs.get("href"), "text": label})
        if tag in {"p", "br", "div", "section", "article", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if self._skip_stack and self._skip_stack[-1] == tag:
            self._skip_stack.pop()
            self._skip = bool(self._skip_stack)
        if tag in {"p", "li", "h1", "h2", "h3"}:
            self.text_parts.append("\n")

    def handle_data(self, data):
        if self._skip:
            return
        text = html.unescape(data or "").strip()
        if not text:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
        self.text_parts.append(text)

    def readable_text(self):
        text = " ".join(part.strip() for part in self.text_parts if part.strip())
        text = re.sub(r"\s+", " ", text).strip()
        return text


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False)
    except Exception:
        return "{}"


def _csv_env(name: str) -> list[str]:
    return [item.strip().lower() for item in os.getenv(name, "").split(",") if item.strip()]


class ComputerBrowserService:
    """Camada de navegador operacional com politica, logs e ponte Browserbase/Stagehand."""

    def __init__(self):
        self.db_path = db_path()
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_sessions (
                    id TEXT PRIMARY KEY,
                    goal TEXT,
                    start_url TEXT,
                    provider TEXT,
                    mode TEXT,
                    status TEXT,
                    live_url TEXT,
                    recording_url TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    kind TEXT,
                    message TEXT,
                    payload TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS browser_approvals (
                    id TEXT PRIMARY KEY,
                    session_id TEXT,
                    instruction TEXT,
                    url TEXT,
                    impact TEXT,
                    reason TEXT,
                    status TEXT,
                    result TEXT,
                    created_at TEXT,
                    decided_at TEXT
                )
                """
            )

    def _node_path(self) -> str:
        configured = os.getenv("BROWSER_AGENT_NODE") or os.getenv("NODE_BINARY")
        if configured and os.path.exists(configured):
            return configured
        candidates = [
            os.path.join(os.getenv("ProgramFiles", r"C:\Program Files"), "nodejs", "node.exe"),
            os.path.join(os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)"), "nodejs", "node.exe"),
            os.path.join(os.path.expanduser("~"), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "node", "bin", "node.exe"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate
        return "node"

    def _runner_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "browser_agent_runner.mjs")

    def _browserbase_ready(self) -> bool:
        return bool(os.getenv("BROWSERBASE_API_KEY") and os.getenv("BROWSERBASE_PROJECT_ID"))

    def _stagehand_enabled(self) -> bool:
        return os.getenv("BROWSER_AGENT_ENABLE_STAGEHAND", "").lower() in {"1", "true", "yes", "sim"}

    def allowed_domains(self) -> list[str]:
        return _csv_env("BROWSER_ALLOWED_DOMAINS")

    def _domain_allowed(self, url: str, for_action: bool = False) -> tuple[bool, str]:
        parsed = urlparse(url or "")
        if not parsed.scheme or not parsed.netloc:
            return False, "URL invalida."
        domain = (parsed.hostname or "").lower()
        allowed = self.allowed_domains()
        if not allowed:
            if for_action and os.getenv("BROWSER_REQUIRE_ALLOWLIST_FOR_ACTIONS", "1").lower() not in {"0", "false", "no", "nao"}:
                return False, "Acoes no navegador exigem BROWSER_ALLOWED_DOMAINS configurado."
            return True, "Dominio permitido por politica ampla de leitura."
        if any(domain == item or domain.endswith(f".{item}") for item in allowed):
            return True, "Dominio permitido."
        return False, f"Dominio fora da allowlist: {domain}"

    def _classify(self, instruction: str, url: str = "", mode: str = "read") -> dict:
        text = (instruction or "").lower()
        impact = "high" if any(term in text for term in HIGH_IMPACT_PATTERNS) else "low"
        action_like = any(term in text for term in ["click", "clic", "preench", "digite", "login", "entrar", "baix", "download", "act", "form"])
        if impact == "low" and action_like and mode != "read":
            impact = "medium"
        allowed, allow_reason = self._domain_allowed(url, for_action=impact in {"medium", "high"}) if url else (True, "Sem URL.")
        needs_approval = impact == "high" or mode == "approval" or not allowed
        if mode == "read" and impact == "medium":
            needs_approval = True
        return {
            "impact": impact,
            "mode": mode,
            "allowed": allowed,
            "allow_reason": allow_reason,
            "needs_approval": needs_approval,
        }

    def _log(self, session_id: str | None, kind: str, message: str, payload: dict | None = None):
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO browser_events (session_id, kind, message, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                (session_id, kind, message, _safe_json(payload), _now()),
            )

    def status(self) -> dict:
        with self._connect() as conn:
            pending = conn.execute("SELECT COUNT(*) FROM browser_approvals WHERE status='pending'").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM browser_sessions").fetchone()[0]
        return {
            "provider": "browserbase-stagehand" if self._browserbase_ready() else "local-fetch",
            "browserbase_configured": self._browserbase_ready(),
            "stagehand_enabled": self._stagehand_enabled(),
            "runner_exists": os.path.exists(self._runner_path()),
            "allowed_domains": self.allowed_domains(),
            "pending_approvals": int(pending),
            "sessions": int(sessions),
            "policy": {
                "read": "Pode navegar, buscar, extrair dados e baixar conteudo simples.",
                "prepare": "Pode preencher e preparar, mas acoes sensiveis entram em aprovacao.",
                "approval": "Pede aprovacao antes de qualquer acao de impacto.",
            },
        }

    def create_session(self, goal: str = "", start_url: str = "", mode: str = "read", provider: str = "auto") -> dict:
        session_id = str(uuid.uuid4())
        selected_provider = provider
        if provider == "auto":
            selected_provider = "browserbase-stagehand" if self._browserbase_ready() and self._stagehand_enabled() else "local-fetch"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_sessions
                    (id, goal, start_url, provider, mode, status, live_url, recording_url, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (session_id, goal, start_url, selected_provider, mode, "active", "", "", _now(), _now()),
            )
        self._log(session_id, "session", "Sessao de navegador criada.", {"goal": goal, "start_url": start_url, "mode": mode, "provider": selected_provider})
        return {
            "id": session_id,
            "goal": goal,
            "start_url": start_url,
            "provider": selected_provider,
            "mode": mode,
            "status": "active",
        }

    def sessions(self, limit: int = 12) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browser_sessions ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit or 12), 50)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def events(self, limit: int = 30) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browser_events ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit or 30), 120)),),
            ).fetchall()
        events = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.get("payload") or "{}")
            events.append(item)
        return events

    def fetch_page(self, url: str, limit: int = 6000) -> dict:
        allowed, reason = self._domain_allowed(url, for_action=False)
        if not allowed:
            return {"ok": False, "url": url, "error": reason}
        response = requests.get(
            url,
            headers={"User-Agent": "AssistenteElite/1.0 local browser reader"},
            timeout=20,
        )
        content_type = response.headers.get("content-type", "")
        parser = _ReadableHTMLParser()
        if "html" in content_type.lower():
            parser.feed(response.text)
            text = parser.readable_text()
            title = parser.title or url
        else:
            text = response.text[:limit]
            title = url
        payload = {
            "ok": response.ok,
            "url": response.url,
            "status_code": response.status_code,
            "title": title[:180],
            "content_type": content_type,
            "text": text[: max(600, min(int(limit or 6000), 20000))],
        }
        self._log(None, "fetch", f"Pagina lida: {url}", {"status_code": response.status_code, "title": payload["title"]})
        return payload

    def _create_approval(self, session_id: str | None, instruction: str, url: str, policy: dict) -> dict:
        approval_id = str(uuid.uuid4())
        reason = policy["allow_reason"] if not policy["allowed"] else f"Acao de impacto {policy['impact']} requer aprovacao humana."
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO browser_approvals
                    (id, session_id, instruction, url, impact, reason, status, result, created_at, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (approval_id, session_id, instruction, url, policy["impact"], reason, "pending", "", _now(), ""),
            )
        self._log(session_id, "approval", "Acao enviada para aprovacao.", {"approval_id": approval_id, "reason": reason})
        return {
            "status": "needs_approval",
            "approval_id": approval_id,
            "impact": policy["impact"],
            "reason": reason,
            "instruction": instruction,
            "url": url,
        }

    def run_instruction(self, instruction: str, url: str = "", mode: str = "read", session_id: str | None = None, force: bool = False) -> dict:
        mode = (mode or "read").lower()
        policy = self._classify(instruction, url, mode)
        if policy["needs_approval"] and not force:
            return self._create_approval(session_id, instruction, url, policy)

        if url and mode == "read":
            fetched = self.fetch_page(url)
            fetched["instruction"] = instruction
            fetched["policy"] = policy
            fetched["status"] = "completed" if fetched.get("ok") else "error"
            return fetched

        if self._browserbase_ready() and self._stagehand_enabled():
            return self._run_stagehand(instruction, url, mode, session_id)

        result = {
            "status": "prepared",
            "provider": "local-fetch",
            "instruction": instruction,
            "url": url,
            "policy": policy,
            "message": "Stagehand/Browserbase ainda nao configurado. A tarefa foi preparada e registrada; leitura de pagina ja funciona pelo fetch local.",
        }
        self._log(session_id, "prepared", "Instrucao preparada para navegador operacional.", result)
        return result

    def _run_stagehand(self, instruction: str, url: str, mode: str, session_id: str | None) -> dict:
        payload = {"instruction": instruction, "url": url, "mode": mode, "sessionId": session_id}
        try:
            completed = subprocess.run(
                [self._node_path(), self._runner_path(), json.dumps(payload, ensure_ascii=False)],
                cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                capture_output=True,
                text=True,
                timeout=int(os.getenv("BROWSER_AGENT_TIMEOUT_SECONDS", "120")),
                shell=False,
                env=self._node_env(),
            )
            raw = completed.stdout.strip() or completed.stderr.strip()
            try:
                result = json.loads(raw)
            except Exception:
                result = {"status": "error", "output": raw, "returncode": completed.returncode}
            self._log(session_id, "stagehand", "Execucao Stagehand concluida.", result)
            return result
        except Exception as exc:
            result = {"status": "error", "provider": "browserbase-stagehand", "error": str(exc)}
            self._log(session_id, "stagehand_error", "Falha ao executar Stagehand.", result)
            return result

    def _node_env(self) -> dict:
        env = os.environ.copy()
        candidates = [
            os.path.join(os.getcwd(), "node_modules"),
            os.path.join(bundle_dir(), "node_modules"),
            os.path.join(exe_dir(), "node_modules"),
            os.path.join(os.path.dirname(exe_dir()), "node_modules"),
        ]
        existing = [path for path in candidates if os.path.isdir(path)]
        current = env.get("NODE_PATH", "")
        if existing:
            env["NODE_PATH"] = os.pathsep.join(existing + ([current] if current else []))
        return env

    def pending_approvals(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM browser_approvals WHERE status='pending' ORDER BY created_at DESC LIMIT ?",
                (max(1, min(int(limit or 20), 100)),),
            ).fetchall()
        return [dict(row) for row in rows]

    def decide_approval(self, approval_id: str, approved: bool, note: str = "") -> dict:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM browser_approvals WHERE id=?", (approval_id,)).fetchone()
            if not row:
                return {"status": "not_found", "approval_id": approval_id}
            if row["status"] != "pending":
                return {"status": row["status"], "approval_id": approval_id, "result": row["result"]}

        if not approved:
            result = {"status": "rejected", "note": note}
            with self._connect() as conn:
                conn.execute(
                    "UPDATE browser_approvals SET status=?, result=?, decided_at=? WHERE id=?",
                    ("rejected", _safe_json(result), _now(), approval_id),
                )
            self._log(row["session_id"], "approval_rejected", "Acao rejeitada pelo usuario.", {"approval_id": approval_id, "note": note})
            return result

        result = self.run_instruction(row["instruction"], row["url"], "prepare", row["session_id"], force=True)
        with self._connect() as conn:
            conn.execute(
                "UPDATE browser_approvals SET status=?, result=?, decided_at=? WHERE id=?",
                ("approved", _safe_json(result), _now(), approval_id),
            )
        self._log(row["session_id"], "approval_approved", "Acao aprovada pelo usuario.", {"approval_id": approval_id})
        return {"status": "approved", "approval_id": approval_id, "result": result}


computer_browser = ComputerBrowserService()
