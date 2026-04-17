from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .db import count_documents, init_db, list_documents
from .rag import ask_question, ingest_document, seed_demo_documents

app = FastAPI(
    title="Local RAG API",
    version="1.0.0",
    description="Ollama + pgvector + FastAPI tabanlı minimal RAG demo API",
)


class DocumentIngestRequest(BaseModel):
    source: str = Field(..., description="Doküman adı veya kaynak etiketi")
    text: str = Field(..., description="Doküman içeriği")
    chunk_size: int = Field(800, ge=100, le=4000)
    overlap: int = Field(150, ge=0, le=1000)


class AskRequest(BaseModel):
    question: str = Field(..., description="Kullanıcı sorusu")
    top_k: int = Field(3, ge=1, le=10)


@app.on_event("startup")
def startup_event():
    init_db()


@app.get("/")
def root():
    return {
        "message": "RAG API ayakta.",
        "endpoints": {
            "health": "/health",
            "seed_demo": "/seed-demo",
            "add_document": "/documents",
            "list_documents": "/documents",
            "ask": "/ask",
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


@app.post("/seed-demo")
def seed_demo():
    try:
        return seed_demo_documents()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/documents")
def add_document(payload: DocumentIngestRequest):
    try:
        result = ingest_document(
            source=payload.source,
            text=payload.text,
            chunk_size=payload.chunk_size,
            overlap=payload.overlap,
        )
        return {
            "message": "Doküman başarıyla eklendi.",
            **result,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/documents")
def get_documents():
    try:
        return {
            "count": count_documents(),
            "items": list_documents(),
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