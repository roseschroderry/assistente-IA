import json
import os
import re
import sqlite3
import subprocess
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any

from dotenv import load_dotenv

from .app_paths import bundle_dir, data_dir, db_path, user_files_dir

load_dotenv()


INDEX_EXTENSIONS = {
    ".exe": "app",
    ".lnk": "app",
    ".bat": "script",
    ".cmd": "script",
    ".ps1": "script",
    ".xlsx": "spreadsheet",
    ".xls": "spreadsheet",
    ".csv": "spreadsheet",
    ".docx": "document",
    ".doc": "document",
    ".pptx": "presentation",
    ".ppt": "presentation",
    ".pdf": "pdf",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".html": "code",
    ".css": "code",
    ".json": "code",
    ".txt": "text",
    ".md": "text",
}

SKIP_DIRS = {
    "$recycle.bin",
    ".git",
    "__pycache__",
    "node_modules",
    "site-packages",
    "windows",
    "winsxs",
    "system volume information",
    "cache",
    "tmp",
    "temp",
}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _safe_json(value: Any) -> str:
    try:
        return json.dumps(value or {}, ensure_ascii=False)
    except Exception:
        return "{}"


def _normalize(value: str) -> str:
    value = (value or "").lower()
    value = re.sub(r"[_\-.]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


class BrainService:
    def __init__(self):
        self.db_path = db_path()
        self._lock = threading.Lock()
        self._scan_thread = None
        self.status = {
            "running": False,
            "last_started": None,
            "last_finished": None,
            "items": 0,
            "scanned": 0,
            "message": "Aguardando primeira varredura.",
        }
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    path TEXT NOT NULL UNIQUE,
                    extension TEXT,
                    size INTEGER,
                    modified REAL,
                    source TEXT,
                    metadata TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_brain_items_name ON brain_items(normalized_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_brain_items_kind ON brain_items(kind)")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    content TEXT,
                    tags TEXT,
                    source_path TEXT,
                    created_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_flows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE,
                    steps TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS brain_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    message TEXT,
                    channels TEXT,
                    status TEXT,
                    created_at TEXT
                )
                """
            )

    def _default_roots(self):
        home = os.path.expanduser("~")
        roots = [
            ("Desktop", os.path.join(home, "Desktop"), 3),
            ("Documents", os.path.join(home, "Documents"), 5),
            ("Downloads", os.path.join(home, "Downloads"), 3),
            ("AssistenteFiles", user_files_dir(), 5),
            ("AssistenteProjeto", bundle_dir(), 4),
            ("StartMenuUser", os.path.join(os.getenv("APPDATA", ""), "Microsoft", "Windows", "Start Menu"), 6),
            ("StartMenuAll", os.path.join(os.getenv("PROGRAMDATA", ""), "Microsoft", "Windows", "Start Menu"), 6),
            ("ProgramFiles", os.getenv("ProgramFiles", r"C:\Program Files"), 4),
            ("ProgramFilesX86", os.getenv("ProgramFiles(x86)", r"C:\Program Files (x86)"), 4),
        ]
        extra_roots = [p.strip() for p in os.getenv("ELITE_SCAN_PATHS", "").split(";") if p.strip()]
        roots.extend((f"Extra{index}", path, 5) for index, path in enumerate(extra_roots, 1))
        return [(source, path, depth) for source, path, depth in roots if path and os.path.exists(path)]

    def _kind_for_path(self, path: str) -> str | None:
        if os.path.isdir(path):
            return "folder"
        return INDEX_EXTENSIONS.get(os.path.splitext(path)[1].lower())

    def _iter_paths(self, root: str, max_depth: int):
        root = os.path.abspath(root)
        base_depth = root.rstrip(os.sep).count(os.sep)
        for current, dirs, files in os.walk(root):
            depth = current.rstrip(os.sep).count(os.sep) - base_depth
            dirs[:] = [
                d for d in dirs
                if d.lower() not in SKIP_DIRS and not d.startswith(".") and depth < max_depth
            ]
            yield current
            for filename in files:
                ext = os.path.splitext(filename)[1].lower()
                if ext in INDEX_EXTENSIONS:
                    yield os.path.join(current, filename)

    def _row_for_path(self, path: str, source: str):
        try:
            kind = self._kind_for_path(path)
            if not kind:
                return None
            stat = os.stat(path)
            name = os.path.splitext(os.path.basename(path))[0] if kind != "folder" else os.path.basename(path)
            metadata = {}
            if kind == "app" and path.lower().endswith(".lnk"):
                target = self._resolve_shortcut(path)
                if target:
                    metadata["target"] = target
            return {
                "name": name,
                "normalized_name": _normalize(name),
                "kind": kind,
                "path": os.path.abspath(path),
                "extension": os.path.splitext(path)[1].lower(),
                "size": stat.st_size if os.path.isfile(path) else None,
                "modified": stat.st_mtime,
                "source": source,
                "metadata": _safe_json(metadata),
                "updated_at": _now(),
            }
        except Exception:
            return None

    def _resolve_shortcut(self, path: str) -> str | None:
        try:
            import win32com.client as win32
            shell = win32.Dispatch("WScript.Shell")
            shortcut = shell.CreateShortcut(path)
            return shortcut.Targetpath or None
        except Exception:
            return None

    def _upsert_rows(self, rows):
        if not rows:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT INTO brain_items
                    (name, normalized_name, kind, path, extension, size, modified, source, metadata, updated_at)
                VALUES
                    (:name, :normalized_name, :kind, :path, :extension, :size, :modified, :source, :metadata, :updated_at)
                ON CONFLICT(path) DO UPDATE SET
                    name=excluded.name,
                    normalized_name=excluded.normalized_name,
                    kind=excluded.kind,
                    extension=excluded.extension,
                    size=excluded.size,
                    modified=excluded.modified,
                    source=excluded.source,
                    metadata=excluded.metadata,
                    updated_at=excluded.updated_at
                """,
                rows,
            )

    def start_background_scan(self, reason: str = "manual") -> dict:
        with self._lock:
            if self._scan_thread and self._scan_thread.is_alive():
                return self.status_summary()
            self._scan_thread = threading.Thread(target=self.scan_machine, args=(reason,), daemon=True)
            self._scan_thread.start()
            return self.status_summary()

    def scan_machine(self, reason: str = "manual") -> dict:
        max_items = int(os.getenv("ELITE_SCAN_MAX_ITEMS", "12000"))
        batch = []
        scanned = 0
        inserted = 0
        self.status.update({
            "running": True,
            "last_started": _now(),
            "message": f"Varredura iniciada: {reason}",
            "scanned": 0,
        })
        try:
            for source, root, depth in self._default_roots():
                for path in self._iter_paths(root, depth):
                    row = self._row_for_path(path, source)
                    scanned += 1
                    if row:
                        batch.append(row)
                    if len(batch) >= 300:
                        self._upsert_rows(batch)
                        inserted += len(batch)
                        batch.clear()
                    if scanned % 300 == 0:
                        self.status.update({"scanned": scanned, "items": self.count_items()})
                    if scanned >= max_items:
                        break
                if scanned >= max_items:
                    break
            self._upsert_rows(batch)
            inserted += len(batch)
            self.status.update({
                "running": False,
                "last_finished": _now(),
                "scanned": scanned,
                "items": self.count_items(),
                "message": f"Varredura concluida. Itens processados: {scanned}. Itens novos/atualizados: {inserted}.",
            })
        except Exception as exc:
            self.status.update({
                "running": False,
                "last_finished": _now(),
                "message": f"Erro na varredura: {exc}",
            })
        return self.status_summary()

    def count_items(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM brain_items").fetchone()[0])

    def status_summary(self) -> dict:
        summary = dict(self.status)
        summary["items"] = self.count_items()
        with self._connect() as conn:
            summary["notes"] = int(conn.execute("SELECT COUNT(*) FROM brain_notes").fetchone()[0])
            summary["flows"] = int(conn.execute("SELECT COUNT(*) FROM brain_flows").fetchone()[0])
        return summary

    def index_path(self, path: str, source: str = "manual") -> dict:
        full_path = os.path.abspath(os.path.expandvars(os.path.expanduser(path)))
        row = self._row_for_path(full_path, source)
        if not row:
            return {"ok": False, "path": full_path, "message": "Caminho nao indexavel ou inexistente."}
        self._upsert_rows([row])
        return {"ok": True, "path": full_path, "kind": row["kind"], "name": row["name"]}

    def search_items(self, query: str, kind: str | None = None, limit: int = 10) -> list[dict]:
        normalized = _normalize(query)
        if not normalized:
            return []
        limit = max(1, min(int(limit or 10), 50))
        raw_query = (query or "").lower().strip()
        params = [f"%{normalized}%", f"%{raw_query}%"]
        where = "(normalized_name LIKE ? OR lower(path) LIKE ?)"
        if kind:
            where += " AND kind = ?"
            params.append(kind)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM brain_items WHERE {where} ORDER BY modified DESC LIMIT ?",
                params + [limit * 3],
            ).fetchall()
            if len(rows) < limit:
                rows = conn.execute(
                    "SELECT * FROM brain_items ORDER BY modified DESC LIMIT ?",
                    (min(1200, limit * 120),),
                ).fetchall()
        ranked = []
        for row in rows:
            score = SequenceMatcher(None, normalized, row["normalized_name"]).ratio()
            if normalized in row["normalized_name"]:
                score += 0.55
            if row["normalized_name"].startswith(normalized):
                score += 0.25
            item = dict(row)
            item["score"] = round(score, 3)
            item["metadata"] = json.loads(item.get("metadata") or "{}")
            ranked.append(item)
        ranked.sort(key=lambda item: (item["score"], item.get("modified") or 0), reverse=True)
        return ranked[:limit]

    def open_item(self, query: str, background: bool = True, kind: str | None = None) -> str:
        matches = self.search_items(query, kind=kind, limit=1)
        if not matches:
            direct_path = os.path.abspath(os.path.expandvars(os.path.expanduser(query or "")))
            if os.path.exists(direct_path):
                try:
                    if background and os.path.isfile(direct_path):
                        subprocess.Popen([direct_path], cwd=os.path.dirname(direct_path) or None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        os.startfile(direct_path)
                    self.index_path(direct_path, "abertura-direta")
                    return f"Abrindo caminho direto: {direct_path}"
                except Exception as exc:
                    return f"Encontrei o caminho direto, mas nao consegui abrir: {exc}"
            return f"Nao encontrei '{query}' no cerebro local. A varredura pode ainda estar rodando."
        item = matches[0]
        path = item["metadata"].get("target") or item["path"]
        try:
            if item["kind"] in {"app", "script"} and background and os.path.splitext(path)[1].lower() in {".exe", ".bat", ".cmd", ".ps1"}:
                command = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", path] if path.lower().endswith(".ps1") else [path]
                subprocess.Popen(command, cwd=os.path.dirname(path) or None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                os.startfile(path)
            return f"Abrindo {item['kind']}: {item['name']} em {path}"
        except Exception as exc:
            return f"Encontrei {item['name']}, mas nao consegui abrir: {exc}"

    def remember(self, title: str, content: str, tags: str = "", source_path: str = "") -> str:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO brain_notes (title, content, tags, source_path, created_at) VALUES (?, ?, ?, ?, ?)",
                (title, content, tags, source_path, _now()),
            )
        return f"Memoria salva no cerebro: {title}"

    def recall(self, query: str = "", limit: int = 8) -> str:
        normalized = f"%{query.lower()}%" if query else "%"
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT title, content, tags, source_path, created_at
                FROM brain_notes
                WHERE lower(title || ' ' || content || ' ' || tags || ' ' || source_path) LIKE ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (normalized, max(1, min(int(limit or 8), 30))),
            ).fetchall()
        if not rows:
            return "Nao encontrei memorias salvas para essa busca."
        return "\n\n".join(
            f"{row['created_at']} | {row['title']}\n{row['content'][:900]}\nFonte: {row['source_path'] or '-'}"
            for row in rows
        )

    def save_flow(self, name: str, steps: list[str]) -> str:
        payload = json.dumps(steps or [], ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO brain_flows (name, steps, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET steps=excluded.steps, updated_at=excluded.updated_at
                """,
                (name, payload, _now(), _now()),
            )
        return f"Fluxo '{name}' salvo com {len(steps or [])} passos."

    def list_flows(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute("SELECT name, steps, updated_at FROM brain_flows ORDER BY name").fetchall()
        return [{"name": row["name"], "steps": json.loads(row["steps"] or "[]"), "updated_at": row["updated_at"]} for row in rows]

    def get_flow(self, name: str) -> list[str] | None:
        with self._connect() as conn:
            row = conn.execute("SELECT steps FROM brain_flows WHERE lower(name)=lower(?)", (name,)).fetchone()
        return json.loads(row["steps"] or "[]") if row else None

    def add_notification_event(self, title: str, message: str, channels: list[str], status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO brain_notifications (title, message, channels, status, created_at) VALUES (?, ?, ?, ?, ?)",
                (title, message, json.dumps(channels or [], ensure_ascii=False), status, _now()),
            )

    def recent_notifications(self, limit: int = 20) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title, message, channels, status, created_at FROM brain_notifications ORDER BY id DESC LIMIT ?",
                (max(1, min(limit, 100)),),
            ).fetchall()
        return [
            {
                "title": row["title"],
                "message": row["message"],
                "channels": json.loads(row["channels"] or "[]"),
                "status": row["status"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]


brain = BrainService()
