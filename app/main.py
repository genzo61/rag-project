import logging
import json
import re
import time
import uuid
from logging.handlers import RotatingFileHandler
from time import perf_counter
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Any

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
from .db import count_documents, delete_by_source, init_db, list_documents, list_sources
from .rag import ask_question, ingest_pdf, normalize_source
from .orchestrator import answer_chat

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

API_MODEL_ID = "local-rag"
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


def _build_chat_completion_response(
    completion_id: str,
    created_ts: int,
    model: str,
    answer: str,
) -> dict[str, Any]:
    return {
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


def _safe_json(value: Any, limit: int = 8000) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = str(value)
    return text[:limit]

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


@app.get("/")
def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return {"message": "RAG API ayakta."}


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
def chat(payload: OrchestratedChatRequest):
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

        result = answer_chat(
            question=question,
            top_k=payload.top_k,
            source = payload.source,
            web_top_k = payload.web_top_k,
            history=history,
        )
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
def chat_completions(payload: ChatCompletionRequest):
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
        )

        answer = result.get("answer", "") or ""
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

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        return _build_chat_completion_response(
            completion_id=completion_id,
            created_ts=created_ts,
            model=model_name,
            answer=answer,
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
