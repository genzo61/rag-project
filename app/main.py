import logging
import json
import os
import re
import threading
import time
import uuid
from collections import OrderedDict
from html import escape
from logging.handlers import RotatingFileHandler
from time import perf_counter
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any
from dotenv import load_dotenv

from .chat_store import (
    add_message,
    create_session,
    delete_session,
    ensure_session,
    get_messages,
    get_session,
    init_chat_store,
    list_sessions,
    update_session_title,
)
from .dp_knowledge_seed import seed_dp_assistant_knowledge
from .db import count_documents, delete_by_source, init_db, list_documents, list_sources
from .rag import PRIMARY_LLM_MODEL, ask_question, ingest_pdf, normalize_source
from .orchestrator import answer_chat

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

def configure_logging() -> None:
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # aynı handler'ları iki kere eklememek için
    if not root.handlers:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root.addHandler(console_handler)

        file_handler = RotatingFileHandler(
            log_dir / "app.log",
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)


configure_logging()
logger = logging.getLogger("rag.api")

API_MODEL_ID = (os.getenv("LOCAL_CHAT_MODEL_ID", "") or PRIMARY_LLM_MODEL or "local-rag").strip()
STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="Local RAG API",
    version="2.2.0",
    description="PDF tabanlı RAG API (OpenRouter/Ollama + pgvector + FastAPI)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

DEBUG_TRACE_STORE: OrderedDict[str, dict[str, Any]] = OrderedDict()
DEBUG_TRACE_LIMIT = int(os.getenv("DEBUG_TRACE_LIMIT", "100"))


def _env_flag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _seed_dp_assistant_knowledge_safe() -> None:
    try:
        seed_dp_assistant_knowledge()
    except Exception as exc:
        logger.exception("startup_seed_dp_assistant_knowledge_failed error=%s", exc)

@app.middleware("http")
async def log_request_timing(request: Request, call_next):
    start = perf_counter()
    try:
        response = await call_next(request)
        duration_ms = (perf_counter() - start) * 1000
        logger.info(
            "%s %s -> %s in %.1f ms",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.1f}"
        response.headers["Cache-Control"] = "no-store"
        return response
    except Exception:
        duration_ms = (perf_counter() - start) * 1000
        logger.exception(
            "%s %s failed in %.1f ms",
            request.method,
            request.url.path,
            duration_ms,
        )
        raise

class AskRequest(BaseModel):
    question: str = Field(..., description="Kullanıcı sorusu")
    top_k: int = Field(8, ge=1, le=10)
    source: str | None = Field(None, description="Sadece belirli bir source içinde ara")
    use_web: bool = Field(False, description="Web search (SearXNG) kullanılsın mı?")
    web_top_k: int = Field(5, ge=1, le=20, description="Web search max sonuç sayısı")

class OrchestratedChatRequest(BaseModel):
    question: str | None = Field(None, description="Kullanıcı sorusu")
    message: str | None = None
    prompt: str | None = None
    input: str | None = None
    messages: list[Any] | None = None
    history: Any | None = None
    session_id: str | None = None
    sessionId: str | None = None
    conversation_id: str | None = None
    conversationId: str | None = None
    chat_id: str | None = None
    chatId: str | None = None
    top_k: int = Field(8, ge=1, le=10)
    source: str | None = Field(None)
    web_top_k: int = Field(5, ge=1, le=20)
    conversation_context: str | None = Field(None)


class CreateChatSessionRequest(BaseModel):
    title: str | None = None


class UpdateChatSessionRequest(BaseModel):
    title: str


class ChatBackupMessage(BaseModel):
    role: str
    content: Any | None = None


class ChatBackupRequest(BaseModel):
    title: str | None = None
    messages: list[ChatBackupMessage] = Field(default_factory=list)


class PdfIngestRequest(BaseModel):
    source: str | None = Field(None, description="Kaynak adı, boş bırakılırsa otomatik üretilir")
    pdf_path: str = Field(..., description="PDF dosya yolu")
    chunk_size: int = Field(1200, ge=200, le=5000)
    overlap: int = Field(200, ge=0, le=1000)
    replace_existing: bool = Field(
        False,
        description="Aynı source varsa önce eski kayıtları sil",
    )

class ChatMessage(BaseModel):
    role: str
    content: str | list[dict[str, Any]] | None = None


class ChatCompletionRequest(BaseModel):
    model: str = Field(API_MODEL_ID)
    messages: list[ChatMessage]
    stream: bool = Field(False)
    top_k: int = Field(8, ge=1, le=10)
    source: str | None = Field(None)
    use_web: bool | None = Field(None)
    web_top_k: int = Field(5, ge=1, le=20)
    files: Any | None = Field(None)
    documents: Any | None = Field(None)
    attachments: Any | None = Field(None)
    citations: Any | None = Field(None)
    metadata: Any | None = Field(None)


def _message_content_to_text(content: str | list[dict[str, Any]] | None) -> str:
    def unwrap_task_prompt(text: str) -> str:
        t = (text or "").strip()
        if not t:
            return ""

        # Open WebUI "Respond to query using <context> ... </context> <actual question>"
        if "</context>" in t:
            tail = t.rsplit("</context>", 1)[-1].strip()
            if tail:
                return tail

        # Open WebUI chat-history wrapper; pick the latest USER line.
        if "<chat_history>" in t and "USER:" in t:
            user_lines = re.findall(r"USER:\s*(.+)", t)
            if user_lines:
                return user_lines[-1].strip()

        return t

    if isinstance(content, str):
        return unwrap_task_prompt(content)

    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return unwrap_task_prompt("\n".join(parts))

    return ""


def _message_role(message: Any) -> str:
    if isinstance(message, ChatMessage):
        return message.role
    if isinstance(message, dict):
        return str(message.get("role") or "")
    return str(getattr(message, "role", "") or "")


def _message_content(message: Any) -> str | list[dict[str, Any]] | None:
    if isinstance(message, ChatMessage):
        return message.content
    if isinstance(message, dict):
        return message.get("content")
    return getattr(message, "content", None)


def _extract_question_from_messages(messages: list[Any]) -> str:
    for message in reversed(messages):
        if _message_role(message) == "user":
            text = _message_content_to_text(_message_content(message))
            if text:
                return text

    if messages:
        return _message_content_to_text(_message_content(messages[-1]))

    return ""


def _history_from_messages(messages: list[Any]) -> list[dict[str, str]]:
    history: list[dict[str, str]] = []
    for message in messages[:-1]:
        role = _message_role(message)
        if role not in {"user", "assistant"}:
            continue
        text = _message_content_to_text(_message_content(message))
        if text:
            history.append({"role": role, "content": text})
    return history


def _history_from_payload_history(history_value: Any) -> list[dict[str, str]]:
    if not isinstance(history_value, list):
        return []
    history: list[dict[str, str]] = []
    for item in history_value:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content") or item.get("message") or item.get("text")
        if role not in {"user", "assistant"}:
            continue
        text = _message_content_to_text(content)
        if text:
            history.append({"role": role, "content": text})
    return history


def _extract_session_id(payload: OrchestratedChatRequest) -> str | None:
    for value in (
        payload.session_id,
        payload.sessionId,
        payload.conversation_id,
        payload.conversationId,
        payload.chat_id,
        payload.chatId,
    ):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _extract_orchestrated_question(payload: OrchestratedChatRequest) -> str:
    for value in (payload.question, payload.message, payload.prompt, payload.input):
        if isinstance(value, str) and value.strip():
            return value.strip()

    if payload.messages:
        return _extract_question_from_messages(payload.messages)

    return ""


def _extract_conversation_context(messages: list[ChatMessage], max_turns: int = 6) -> str:
    if not messages:
        return ""

    normalized: list[tuple[str, str]] = []
    latest_user_index = -1

    for message in messages:
        role = (message.role or "").strip().lower()
        if role == "system":
            continue

        text = _message_content_to_text(message.content)
        if not text:
            continue

        normalized.append((role, text))
        if role == "user":
            latest_user_index = len(normalized) - 1

    if not normalized:
        return ""

    history_items = normalized[:latest_user_index] if latest_user_index >= 0 else normalized[:-1]
    history_items = history_items[-max_turns:]

    lines: list[str] = []
    for role, text in history_items:
        label = "USER" if role == "user" else "ASSISTANT"
        lines.append(f"{label}: {text}")

    return "\n".join(lines)


def _conversation_context_from_history(
    history: list[dict[str, Any]] | None,
    max_turns: int = 6,
) -> str:
    items = [item for item in (history or []) if str(item.get("content") or "").strip()]
    if not items:
        return ""

    history_items = items[-max_turns:]
    lines: list[str] = []
    for item in history_items:
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        label = "USER" if role == "user" else "ASSISTANT"
        lines.append(f"{label}: {str(item.get('content') or '').strip()}")
    return "\n".join(lines)


def _build_chat_completion_response(
    completion_id: str,
    created_ts: int,
    model: str,
    answer: str,
    debug_trace_id: str | None = None,
    debug_trace_url: str | None = None,
    debug_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = {
        "id": completion_id,
        "object": "chat.completion",
        "created": created_ts,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": answer,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
    if debug_trace_id:
        response["debug_trace_id"] = debug_trace_id
    if debug_trace_url:
        response["debug_trace_url"] = debug_trace_url
    if debug_trace:
        response["debug_trace"] = debug_trace
    return response


def _safe_json(value: Any, limit: int = 8000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    return text[:limit]


def _runtime_ui_config() -> dict[str, str]:
    return {
        "apiBaseUrl": (
            os.getenv("RAG_UI_API_BASE_URL", "")
            or os.getenv("DEBUG_TRACE_BASE_URL", "")
        ).strip().rstrip("/"),
        "model": (os.getenv("RAG_UI_MODEL_ID", "") or API_MODEL_ID).strip(),
    }


def _store_debug_trace(
    trace: dict[str, Any] | None,
    request: Request | None = None,
) -> tuple[str | None, str | None]:
    if not trace:
        return None, None

    trace_id = uuid.uuid4().hex
    DEBUG_TRACE_STORE[trace_id] = trace
    while len(DEBUG_TRACE_STORE) > DEBUG_TRACE_LIMIT:
        DEBUG_TRACE_STORE.popitem(last=False)
    path = f"/debug/traces/{trace_id}"
    explicit_base_url = (
        os.getenv("DEBUG_TRACE_BASE_URL", "") or os.getenv("PUBLIC_BASE_URL", "")
    ).strip().rstrip("/")
    if explicit_base_url:
        return trace_id, f"{explicit_base_url}{path}"

    if request is not None:
        forwarded_proto = (request.headers.get("x-forwarded-proto") or "").strip()
        forwarded_host = (request.headers.get("x-forwarded-host") or "").strip()
        forwarded_port = (request.headers.get("x-forwarded-port") or "").strip()
        host_header = (request.headers.get("host") or "").strip()
        scheme = forwarded_proto or request.url.scheme or "http"
        host_value = forwarded_host or host_header

        if host_value and ":" not in host_value and forwarded_port:
            host_value = f"{host_value}:{forwarded_port}"

        if not host_value:
            server = request.scope.get("server")
            if isinstance(server, tuple) and len(server) >= 2:
                server_host = str(server[0] or "127.0.0.1")
                server_port = server[1]
                default_port = 443 if scheme == "https" else 80
                host_value = (
                    f"{server_host}:{server_port}"
                    if server_port and server_port != default_port
                    else server_host
                )

        if host_value and ":" not in host_value:
            server = request.scope.get("server")
            if isinstance(server, tuple) and len(server) >= 2:
                server_port = server[1]
                default_port = 443 if scheme == "https" else 80
                if server_port and server_port != default_port:
                    host_value = f"{host_value}:{server_port}"

        if host_value:
            return trace_id, f"{scheme}://{host_value}{path}"

    return trace_id, path


def _render_debug_trace_html(trace_id: str, trace: dict[str, Any]) -> str:
    summary = trace.get("summary", {})
    routing = trace.get("routing", {})
    tool_trace = list(trace.get("tool_trace") or [])
    sql_queries = list(trace.get("sql_queries") or [])

    sql_sections: list[str] = []
    for index, query in enumerate(sql_queries, start=1):
        params = query.get("params") or []
        params_html = "".join(f"<li><code>{escape(str(item))}</code></li>" for item in params) or "<li><em>none</em></li>"
        sql_sections.append(
            "<section class='card'>"
            f"<h3>SQL #{index}</h3>"
            f"<p><strong>Mode:</strong> {escape(str(query.get('query_mode') or 'unknown'))}</p>"
            f"<p><strong>Rows:</strong> {escape(str(query.get('row_count') or 0))}</p>"
            f"<pre>{escape(str(query.get('sql') or ''))}</pre>"
            f"<details><summary>Parameters</summary><ul>{params_html}</ul></details>"
            "</section>"
        )

    if not sql_sections:
        sql_sections.append("<section class='card'><h3>SQL</h3><p>No SQL query was executed for this answer.</p></section>")

    tool_sections = "".join(
        "<li><code>"
        + escape(json.dumps(item, ensure_ascii=False, default=str))
        + "</code></li>"
        for item in tool_trace
    ) or "<li><em>No tool trace available.</em></li>"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Debug Trace {escape(trace_id)}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #f5f7fb; color: #1f2937; }}
    .wrap {{ max-width: 1100px; margin: 0 auto; }}
    .card {{ background: white; border: 1px solid #dbe3f0; border-radius: 14px; padding: 16px 18px; margin-bottom: 16px; box-shadow: 0 4px 14px rgba(15,23,42,0.05); }}
    h1, h2, h3 {{ margin-top: 0; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0f172a; color: #e5eefc; padding: 14px; border-radius: 10px; overflow-x: auto; }}
    code {{ font-family: Consolas, monospace; }}
    ul {{ padding-left: 20px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; }}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>Answer Debug Trace</h1>
      <p><strong>Trace ID:</strong> <code>{escape(trace_id)}</code></p>
      <div class="grid">
        <div><strong>Route:</strong> {escape(str(routing.get("route") or "unknown"))}</div>
        <div><strong>Confidence:</strong> {escape(str(routing.get("confidence") or ""))}</div>
        <div><strong>SQL Queries:</strong> {escape(str(summary.get("sql_query_count") or 0))}</div>
        <div><strong>DP DB Rows:</strong> {escape(str(summary.get("dp_db_row_count") or 0))}</div>
      </div>
      <p><strong>Reason:</strong> {escape(str(routing.get("reason") or ""))}</p>
    </div>
    <div class="card">
      <h2>Tool Trace</h2>
      <ul>{tool_sections}</ul>
    </div>
    <h2>Executed SQL</h2>
    {''.join(sql_sections)}
  </div>
</body>
</html>"""

def _build_models_response() -> dict[str, Any]:
    created_ts = int(time.time())
    model_ids = [API_MODEL_ID]

    return {
        "object": "list",
        "data": [
            {
                "id": model_id,
                "object": "model",
                "created": created_ts,
                "owned_by": "local",
            }
            for model_id in model_ids
        ],
    }

@app.on_event("startup")
def startup_event():
    init_db()
    init_chat_store()
    if not _env_flag("DP_ASSISTANT_SEED_ON_STARTUP", True):
        logger.info("startup_seed_dp_assistant_knowledge skipped via env")
        return

    if _env_flag("DP_ASSISTANT_SEED_ASYNC", True):
        threading.Thread(
            target=_seed_dp_assistant_knowledge_safe,
            name="dp-assistant-seed",
            daemon=True,
        ).start()
        logger.info("startup_seed_dp_assistant_knowledge scheduled async=true")
        return

    _seed_dp_assistant_knowledge_safe()


@app.get("/")
def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "RAG API ayakta."}


@app.get("/runtime-config.js")
def runtime_config_js():
    payload = json.dumps(_runtime_ui_config(), ensure_ascii=False)
    return Response(
        content=f"window.__RAG_RUNTIME_CONFIG__ = {payload};\n",
        media_type="application/javascript",
    )


@app.get("/debug/traces/{trace_id}", response_class=HTMLResponse)
def get_debug_trace(trace_id: str):
    trace = DEBUG_TRACE_STORE.get(trace_id)
    if not trace:
        raise HTTPException(status_code=404, detail="Debug trace not found.")
    return HTMLResponse(_render_debug_trace_html(trace_id, trace))


@app.get("/health")
def health():
    try:
        total_docs = count_documents()
        return {
            "status": "ok",
            "documents_in_db": total_docs,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents")
def get_documents():
    try:
        return {
            "count": count_documents(),
            "items": list_documents(limit=200),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/ask")
def ask(payload: AskRequest):
    try:
        return ask_question(
            question=payload.question,
            top_k=payload.top_k,
            source=payload.source,
            use_web=payload.use_web,
            web_top_k=payload.web_top_k,
        )
    except Exception as e:
        logger.exception("POST /ask failed: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/chat")
def chat(payload: OrchestratedChatRequest, request: Request):
    try:
        question = _extract_orchestrated_question(payload)
        if not question:
            raise HTTPException(status_code=400, detail="No user message content found.")

        requested_session_id = _extract_session_id(payload)
        if requested_session_id:
            session = ensure_session(requested_session_id)
            if not session:
                session = create_session()
        else:
            session = create_session()

        session_id = session["id"]
        stored_history = get_messages(session_id, limit=500)
        payload_history = _history_from_payload_history(payload.history)
        if payload.messages:
            payload_history.extend(_history_from_messages(payload.messages))
        history = [*stored_history, *payload_history]
        add_message(session_id, "user", question)

        conversation_context = (
            (payload.conversation_context or "").strip()
            or _conversation_context_from_history(history)
        )

        result = answer_chat(
            question=question,
            top_k=payload.top_k,
            source = payload.source,
            web_top_k = payload.web_top_k,
            history=history,
            conversation_context=conversation_context,
        )
        debug_trace_id, debug_trace_url = _store_debug_trace(
            result.get("debug_trace") if isinstance(result, dict) else None,
            request=request,
        )
        if debug_trace_id:
            result["debug_trace_id"] = debug_trace_id
        if debug_trace_url:
            result["debug_trace_url"] = debug_trace_url
        add_message(session_id, "assistant", str(result.get("answer") or ""))
        result["session_id"] = session_id
        result["session"] = get_session(session_id)
        result["messages"] = get_messages(session_id, limit=500)
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))        


@app.post("/chat/sessions")
def create_chat_session(payload: CreateChatSessionRequest | None = None):
    try:
        title = payload.title if payload else ""
        return create_session(title or None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/sessions")
def get_chat_sessions(limit: int = 100):
    try:
        return {"items": list_sessions(limit=limit)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/chat/sessions/{session_id}")
def get_chat_session(session_id: str):
    try:
        session = get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Sohbet bulunamadı.")
        return {
            "session": session,
            "messages": get_messages(session_id, limit=500),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.patch("/chat/sessions/{session_id}")
def patch_chat_session(session_id: str, payload: UpdateChatSessionRequest):
    try:
        session = update_session_title(session_id, payload.title)
        if not session:
            raise HTTPException(status_code=404, detail="Sohbet bulunamadı.")
        return session
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/chat/sessions/{session_id}")
def remove_chat_session(session_id: str):
    try:
        deleted = delete_session(session_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Sohbet bulunamadı.")
        return {"deleted": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat/backup")
def backup_chat(payload: ChatBackupRequest):
    try:
        title = (payload.title or "").strip() or None
        session = create_session(title)
        session_id = session["id"]

        for message in payload.messages:
            role = (message.role or "").strip() or "user"
            content = message.content
            if content is None:
                text = ""
            elif isinstance(content, str):
                text = content
            else:
                text = json.dumps(content, ensure_ascii=False)
            add_message(session_id, role, text)

        return {
            "session_id": session_id,
            "session": get_session(session_id),
            "message_count": len(payload.messages),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/v1/chat/completions")
def chat_completions(payload: ChatCompletionRequest, request: Request):
    try:
        request_diag = {
            "messages": [msg.model_dump() for msg in payload.messages],
            "files": payload.files,
            "documents": payload.documents,
            "attachments": payload.attachments,
            "citations": payload.citations,
            "metadata": payload.metadata,
        }
        logger.info("chat_completions_request_diag=%s", _safe_json(request_diag))

        question = _extract_question_from_messages(payload.messages)
        conversation_context = _extract_conversation_context(payload.messages)
        if not question:
            raise HTTPException(status_code=400, detail="No user message content found.")
        requested_model = payload.model or API_MODEL_ID
        model_name = API_MODEL_ID
        if requested_model != API_MODEL_ID:
            logger.info(
                "chat_completions_model_alias requested=%s served_as=%s",
                requested_model,
                model_name,
            )
        logger.info("chat_completions_routing mode=orchestrated")
        result = answer_chat(
            question=question,
            top_k=payload.top_k,
            source=payload.source,
            web_top_k=payload.web_top_k,
            history=_history_from_messages(payload.messages),
            conversation_context=conversation_context,
        )

        answer = result.get("answer", "") or ""
        debug_trace = result.get("debug_trace") if isinstance(result, dict) else None
        debug_trace_id, debug_trace_url = _store_debug_trace(
            debug_trace if isinstance(debug_trace, dict) else None,
            request=request,
        )
        completion_id = f"chatcmpl-{uuid.uuid4().hex}"
        created_ts = int(time.time())

        if payload.stream:
            def event_stream():
                first_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": answer,
                            },
                            "finish_reason": None,
                        }
                    ],
                }
                end_chunk = {
                    "id": completion_id,
                    "object": "chat.completion.chunk",
                    "created": created_ts,
                    "model": model_name,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": "stop",
                        }
                    ],
                }
                yield f"data: {json.dumps(first_chunk, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps(end_chunk, ensure_ascii=False)}\n\n"
                yield "data: [DONE]\n\n"

            headers = {}
            if debug_trace_url:
                headers["X-Debug-Trace-Url"] = debug_trace_url
            if debug_trace_id:
                headers["X-Debug-Trace-Id"] = debug_trace_id
            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers=headers,
            )

        return _build_chat_completion_response(
            completion_id=completion_id,
            created_ts=created_ts,
            model=model_name,
            answer=answer,
            debug_trace_id=debug_trace_id,
            debug_trace_url=debug_trace_url,
            debug_trace=debug_trace if isinstance(debug_trace, dict) else None,
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/models")
def list_models():
    try:
        return _build_models_response()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/sources")
def get_sources():
    try:
        items = list_sources()
        return {
            "count": len(items),
            "items": items,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 

@app.post("/ingest-pdf")
def ingest_pdf_endpoint(payload: PdfIngestRequest):
    try:
        pdf_file = Path(payload.pdf_path)

        if not pdf_file.exists():
            raise HTTPException(
                status_code=400,
                detail=f"PDF bulunamadı: {payload.pdf_path}",
            )

        raw_source = payload.source.strip() if payload.source else ""
        if not raw_source:
            raw_source = f"{Path(payload.pdf_path).stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        normalized_source = normalize_source(raw_source, payload.pdf_path)

        deleted_existing = 0
        if payload.replace_existing:
            deleted_existing = delete_by_source(normalized_source)

        result = ingest_pdf(
            source=normalized_source,
            pdf_path=str(pdf_file),
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )

        return {
            "message": "PDF başarıyla ingest edildi.",
            "normalized_source": normalized_source,
            "deleted_existing_chunks": deleted_existing,
            **result,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
