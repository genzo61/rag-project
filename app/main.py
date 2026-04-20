from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from time import perf_counter
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from .db import count_documents, delete_by_source, init_db, list_documents, list_sources
from .rag import ask_question, ingest_pdf, normalize_source


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

app = FastAPI(
    title="Local RAG API",
    version="2.2.0",
    description="PDF tabanlı RAG API (OpenRouter/Ollama + pgvector + FastAPI)",
)

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
    top_k: int = Field(3, ge=1, le=10)
    source: str | None = Field(None, description="Sadece belirli bir source içinde ara")


class PdfIngestRequest(BaseModel):
    source: str | None = Field(None, description="Kaynak adı, boş bırakılırsa otomatik üretilir")
    pdf_path: str = Field(..., description="PDF dosya yolu")
    chunk_size: int = Field(1200, ge=200, le=5000)
    overlap: int = Field(200, ge=0, le=1000)
    replace_existing: bool = Field(
        False,
        description="Aynı source varsa önce eski kayıtları sil",
    )


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/")
def root():
    return {
        "message": "RAG API ayakta.",
        "endpoints": {
            "health": "/health",
            "list_documents": "/documents",
            "ask": "/ask",
            "ingest_pdf": "/ingest-pdf",
        },
    }


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
        )
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