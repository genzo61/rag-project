from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .db import count_documents, delete_by_source, init_db, list_documents
from .rag import ask_question, ingest_pdf, normalize_source

app = FastAPI(
    title="Local RAG API",
    version="2.1.0",
    description="PDF tabanlı RAG API (OpenRouter/Ollama + pgvector + FastAPI)",
)


class AskRequest(BaseModel):
    question: str = Field(..., description="Kullanıcı sorusu")
    top_k: int = Field(3, ge=1, le=10)


class PdfIngestRequest(BaseModel):
    source: str = Field(..., description="Kaynak adı, örn: water_main_breaks")
    pdf_path: str = Field(..., description="PDF dosya yolu")
    chunk_size: int = Field(1200, ge=200, le=5000)
    overlap: int = Field(200, ge=0, le=1000)
    replace_existing: bool = Field(
        True,
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
        )
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

        normalized_source = normalize_source(payload.source, payload.pdf_path)

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