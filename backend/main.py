from fastapi import FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
import os
import shutil
import sys
import time
from urllib.parse import urlparse
from .ai_engine import AIEngine
from .voice_engine import voice
from .tools import (
    app_diagnostics,
    available_tools,
    capture_screen_payload,
    get_system_stats,
    analyze_and_remember_file,
    open_by_name,
    send_notification,
    _dangerous_tools_enabled,
    _full_access_enabled,
    _operator_mode_enabled,
)
from .app_paths import log_path, runtime_summary, user_files_dir
from .brain import brain
from .computer_browser import computer_browser

# Ajuste para encontrar o frontend em qualquer modo (App ou Script)
if getattr(sys, 'frozen', False):
    base_path = sys._MEIPASS
else:
    base_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

frontend_path = os.path.join(base_path, "frontend")

app = FastAPI(title="Assistente I.A Elite")

LOCAL_ALLOWED_ORIGINS = {
    "http://127.0.0.1:8008",
    "http://localhost:8008",
    "http://127.0.0.1:8000",
    "http://localhost:8000",
}
PUBLIC_ALLOWED_ORIGINS = {
    origin.strip().rstrip("/")
    for origin in (os.getenv("PUBLIC_ALLOWED_ORIGINS") or "").split(",")
    if origin.strip()
}
ALLOWED_ORIGINS = LOCAL_ALLOWED_ORIGINS | PUBLIC_ALLOWED_ORIGINS

# CORS restrito ao dashboard local do app desktop.
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ai = AIEngine()

class ChatRequest(BaseModel):
    message: str

class SpeakRequest(BaseModel):
    text: str

class MobileChatRequest(BaseModel):
    message: str
    client_id: str = "mobile"

class BrainOpenRequest(BaseModel):
    query: str
    background: bool = True
    kind: str = ""

class BrainRememberRequest(BaseModel):
    title: str
    content: str
    tags: str = ""
    source_path: str = ""

class NotificationRequest(BaseModel):
    title: str = "Assistente Elite"
    message: str
    channels: list[str] | None = None

class FlowRequest(BaseModel):
    name: str
    steps: list[str]

class BrowserSessionRequest(BaseModel):
    goal: str = ""
    start_url: str = ""
    mode: str = "read"
    provider: str = "auto"

class BrowserInstructionRequest(BaseModel):
    instruction: str
    url: str = ""
    mode: str = "read"
    session_id: str = ""

class BrowserFetchRequest(BaseModel):
    url: str
    limit: int = 6000

class BrowserApprovalRequest(BaseModel):
    approved: bool
    note: str = ""

@app.on_event("startup")
async def startup_brain_scan():
    """Indexa maquina e arquivos conhecidos sem bloquear a abertura do app."""
    try:
        brain.start_background_scan("startup")
    except Exception:
        pass

def _is_local_origin(value: str | None) -> bool:
    if not value:
        return True
    if value == "null":
        return False
    normalized = value.strip().rstrip("/")
    if normalized in PUBLIC_ALLOWED_ORIGINS:
        return True
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and parsed.hostname in {"127.0.0.1", "localhost"}

@app.middleware("http")
async def block_non_local_browser_origins(request: Request, call_next):
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    if not _is_local_origin(origin) or not _is_local_origin(referer):
        return JSONResponse({"detail": "Origem nao autorizada."}, status_code=403)
    return await call_next(request)

def _check_mobile_token(value: str | None):
    expected = (os.getenv("MOBILE_CLIENT_TOKEN") or "").strip()
    if expected and value != expected:
        raise HTTPException(status_code=401, detail="Token mobile invalido.")

def _mobile_features():
    return {
        "chat": True,
        "voice": True,
        "voice_cloud": voice.status().get("deepgram_configured", False),
        "tts_cloud": voice.status().get("elevenlabs_configured", False),
        "brain": True,
        "brain_open": True,
        "browser_approvals": True,
        "notifications": True,
        "screen_watch": False,
        "operator_tools": _operator_mode_enabled(),
    }

@app.get("/health")
async def health_endpoint():
    return {
        "status": "online",
        "service": "Assistente Elite",
        "time": time.time(),
        "provider": getattr(ai, "provider", None),
        "model": getattr(ai, "model", None),
        "operator_mode": _operator_mode_enabled(),
        "dangerous_tools": _dangerous_tools_enabled(),
        "full_access": _full_access_enabled(),
        "tools": len(available_tools),
        "tts_available": bool(voice.engine),
        "voice": voice.status(),
        "brain": brain.status_summary(),
        "browser": computer_browser.status(),
        "paths": runtime_summary(),
    }

@app.get("/mobile/bootstrap")
async def mobile_bootstrap_endpoint(x_assistente_mobile_token: str | None = Header(default=None)):
    _check_mobile_token(x_assistente_mobile_token)
    return {
        "app": {
            "name": os.getenv("MOBILE_APP_NAME", "Assistente Elite"),
            "environment": os.getenv("MOBILE_APP_ENV", "production"),
            "api_base_url": os.getenv("MOBILE_PUBLIC_API_BASE_URL", ""),
            "auth_required": bool((os.getenv("MOBILE_CLIENT_TOKEN") or "").strip()),
        },
        "assistant": {
            "provider": getattr(ai, "provider", None),
            "model": getattr(ai, "model", None),
            "tools": len(available_tools),
        },
        "features": _mobile_features(),
        "voice": voice.status(),
        "brain": brain.status_summary(),
        "browser": computer_browser.status(),
        "time": time.time(),
    }

@app.get("/mobile/status")
async def mobile_status_endpoint(x_assistente_mobile_token: str | None = Header(default=None)):
    _check_mobile_token(x_assistente_mobile_token)
    return {
        "status": "online",
        "service": "Assistente Elite",
        "provider": getattr(ai, "provider", None),
        "model": getattr(ai, "model", None),
        "tools": len(available_tools),
        "voice": voice.status(),
        "brain": brain.status_summary(),
        "browser": computer_browser.status(),
        "features": _mobile_features(),
        "time": time.time(),
    }

@app.post("/mobile/chat")
async def mobile_chat_endpoint(
    request: MobileChatRequest,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    with open(log_path("log_requisicoes.txt"), "a", encoding="utf-8") as f:
        f.write(f"Mobile {request.client_id}: {request.message} as {time.ctime()}\n")
    try:
        response = await run_in_threadpool(ai.chat, request.message)
        return {"response": response, "provider": getattr(ai, "provider", None), "model": getattr(ai, "model", None)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    # Log de depuração para o executável
    with open(log_path("log_requisicoes.txt"), "a", encoding="utf-8") as f:
        f.write(f"Recebida mensagem: {request.message} as {time.ctime()}\n")
    try:
        response = ai.chat(request.message)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/clear")
async def clear_endpoint():
    ai.clear_history()
    return {"status": "Histórico limpo"}

@app.get("/stats")
async def stats_endpoint():
    """Retorna estatísticas do sistema para o Dashboard."""
    return get_system_stats()

@app.get("/diagnostics")
async def diagnostics_endpoint():
    """Retorna o diagnostico de prontidao para empacotar como app."""
    return app_diagnostics()

@app.get("/tools/catalog")
async def tools_catalog_endpoint():
    """Lista as ferramentas disponiveis para o dashboard e auditoria."""
    return {
        "count": len(available_tools),
        "tools": [
            {
                "name": tool.get("function", {}).get("name"),
                "description": tool.get("function", {}).get("description"),
            }
            for tool in available_tools
        ],
    }

@app.get("/brain/status")
async def brain_status_endpoint():
    return brain.status_summary()

@app.post("/brain/scan")
async def brain_scan_endpoint():
    return brain.start_background_scan("manual")

@app.get("/brain/search")
async def brain_search_endpoint(
    query: str = Query(..., min_length=1),
    kind: str = "",
    limit: int = 12,
):
    return {"results": brain.search_items(query=query, kind=kind or None, limit=limit)}

@app.post("/brain/open")
async def brain_open_endpoint(request: BrainOpenRequest):
    result = await run_in_threadpool(open_by_name, request.query, request.background, request.kind)
    return {"result": result}

@app.post("/brain/remember")
async def brain_remember_endpoint(request: BrainRememberRequest):
    result = brain.remember(request.title, request.content, request.tags, request.source_path)
    return {"result": result}

@app.get("/brain/recall")
async def brain_recall_endpoint(query: str = "", limit: int = 8):
    return {"result": brain.recall(query=query, limit=limit)}

@app.post("/files/analyze")
async def analyze_uploaded_file(file: UploadFile = File(...)):
    safe_name = os.path.basename(file.filename or f"arquivo_{int(time.time())}")
    upload_dir = os.path.join(user_files_dir(), "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    path = os.path.join(upload_dir, safe_name)
    with open(path, "wb") as target:
        shutil.copyfileobj(file.file, target)
    result = await run_in_threadpool(analyze_and_remember_file, path, f"Upload: {safe_name}", "upload,arquivo")
    return {"path": path, "result": result}

@app.post("/notifications/send")
async def send_notification_endpoint(request: NotificationRequest):
    result = await run_in_threadpool(send_notification, request.title, request.message, request.channels)
    return result

@app.post("/mobile/notifications/send")
async def mobile_send_notification_endpoint(
    request: NotificationRequest,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    result = await run_in_threadpool(send_notification, request.title, request.message, request.channels)
    return result

@app.get("/mobile/brain/status")
async def mobile_brain_status_endpoint(x_assistente_mobile_token: str | None = Header(default=None)):
    _check_mobile_token(x_assistente_mobile_token)
    return brain.status_summary()

@app.post("/mobile/brain/scan")
async def mobile_brain_scan_endpoint(x_assistente_mobile_token: str | None = Header(default=None)):
    _check_mobile_token(x_assistente_mobile_token)
    return brain.start_background_scan("mobile")

@app.get("/mobile/brain/search")
async def mobile_brain_search_endpoint(
    query: str = Query(..., min_length=1),
    kind: str = "",
    limit: int = 12,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    return {"results": brain.search_items(query=query, kind=kind or None, limit=limit)}

@app.post("/mobile/brain/open")
async def mobile_brain_open_endpoint(
    request: BrainOpenRequest,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    result = await run_in_threadpool(open_by_name, request.query, request.background, request.kind)
    return {"result": result}

@app.get("/mobile/browser/status")
async def mobile_browser_status_endpoint(x_assistente_mobile_token: str | None = Header(default=None)):
    _check_mobile_token(x_assistente_mobile_token)
    return computer_browser.status()

@app.get("/mobile/browser/approvals")
async def mobile_browser_approvals_endpoint(
    limit: int = 20,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    return {"approvals": computer_browser.pending_approvals(limit=limit)}

@app.post("/mobile/browser/approvals/{approval_id}")
async def mobile_browser_decide_approval_endpoint(
    approval_id: str,
    request: BrowserApprovalRequest,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    return await run_in_threadpool(computer_browser.decide_approval, approval_id, request.approved, request.note)

@app.get("/notifications/events")
async def notification_events_endpoint(limit: int = 20):
    return {"events": brain.recent_notifications(limit=limit)}

@app.post("/flows")
async def create_flow_endpoint(request: FlowRequest):
    return {"result": brain.save_flow(request.name, request.steps)}

@app.get("/flows")
async def list_flows_endpoint():
    return {"flows": brain.list_flows()}

@app.post("/flows/{name}/run")
async def run_flow_endpoint(name: str):
    from .tools import run_flow

    result = await run_in_threadpool(run_flow, name)
    return {"result": result}

@app.get("/browser/status")
async def browser_status_endpoint():
    return computer_browser.status()

@app.get("/browser/sessions")
async def browser_sessions_endpoint(limit: int = 12):
    return {"sessions": computer_browser.sessions(limit=limit)}

@app.post("/browser/session")
async def browser_session_endpoint(request: BrowserSessionRequest):
    return computer_browser.create_session(
        goal=request.goal,
        start_url=request.start_url,
        mode=request.mode,
        provider=request.provider,
    )

@app.post("/browser/fetch")
async def browser_fetch_endpoint(request: BrowserFetchRequest):
    return await run_in_threadpool(computer_browser.fetch_page, request.url, request.limit)

@app.post("/browser/run")
async def browser_run_endpoint(request: BrowserInstructionRequest):
    return await run_in_threadpool(
        computer_browser.run_instruction,
        request.instruction,
        request.url,
        request.mode,
        request.session_id or None,
    )

@app.get("/browser/approvals")
async def browser_approvals_endpoint(limit: int = 20):
    return {"approvals": computer_browser.pending_approvals(limit=limit)}

@app.post("/browser/approvals/{approval_id}")
async def browser_decide_approval_endpoint(approval_id: str, request: BrowserApprovalRequest):
    return await run_in_threadpool(computer_browser.decide_approval, approval_id, request.approved, request.note)

@app.get("/browser/events")
async def browser_events_endpoint(limit: int = 30):
    return {"events": computer_browser.events(limit=limit)}

@app.post("/voice/listen")
async def voice_listen_endpoint():
    text = await run_in_threadpool(voice.listen)
    ok = bool(text and not text.startswith("Microfone indisponivel") and not text.startswith("Erro no servico"))
    return {"text": text, "ok": ok}

@app.get("/voice/status")
async def voice_status_endpoint():
    return voice.status()

@app.post("/voice/transcribe")
async def voice_transcribe_endpoint(audio: UploadFile = File(...)):
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/webm"
    return await run_in_threadpool(voice.transcribe_audio_bytes, audio_bytes, content_type)

@app.post("/mobile/voice/transcribe")
async def mobile_voice_transcribe_endpoint(
    audio: UploadFile = File(...),
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    audio_bytes = await audio.read()
    content_type = audio.content_type or "audio/mp4"
    return await run_in_threadpool(voice.transcribe_audio_bytes, audio_bytes, content_type)

@app.get("/voice/devices")
async def voice_devices_endpoint():
    names = await run_in_threadpool(voice.list_microphones)
    devices = [{"index": index, "name": name} for index, name in enumerate(names)]
    return {"devices": devices}

@app.post("/voice/tts")
async def voice_tts_endpoint(request: SpeakRequest):
    return await run_in_threadpool(voice.generate_speech_audio, request.text)

@app.post("/mobile/voice/tts")
async def mobile_voice_tts_endpoint(
    request: SpeakRequest,
    x_assistente_mobile_token: str | None = Header(default=None),
):
    _check_mobile_token(x_assistente_mobile_token)
    return await run_in_threadpool(voice.generate_speech_audio, request.text)

@app.post("/voice/speak")
async def voice_speak_endpoint(request: SpeakRequest):
    await run_in_threadpool(voice.speak, request.text)
    return {"status": "ok", "tts_available": bool(voice.engine), "voice": voice.status()}

@app.get("/screen/snapshot")
async def screen_snapshot_endpoint():
    try:
        return await run_in_threadpool(capture_screen_payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Servir arquivos estáticos do dashboard
app.mount("/static", StaticFiles(directory=frontend_path), name="static")

@app.get("/")
async def get_index():
    return FileResponse(os.path.join(frontend_path, "index.html"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
