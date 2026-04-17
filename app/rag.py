import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from .db import count_documents, insert_document, search_similar
from .embeddings import get_embedding

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:3b")

client = OpenAI(
    base_url=f"{OLLAMA_BASE_URL}/v1",
    api_key="ollama",
)


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError("overlap, chunk_size'dan küçük olmalı.")

    chunks: list[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + chunk_size, text_len)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= text_len:
            break

        start = end - overlap

    return chunks


def ingest_document(
    source: str,
    text: str,
    chunk_size: int = 800,
    overlap: int = 150,
) -> dict[str, Any]:
    chunks = chunk_text(text, chunk_size=chunk_size, overlap=overlap)

    if not chunks:
        raise ValueError("Boş doküman ingest edilemez.")

    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk)
        insert_document(
            source=source,
            chunk_index=i,
            content=chunk,
            embedding=embedding,
        )

    return {
        "source": source,
        "chunks_added": len(chunks),
    }


def retrieve_context(question: str, top_k: int = 3) -> dict[str, Any]:
    if count_documents() == 0:
        raise ValueError("Vector database boş. Önce doküman eklemelisin.")

    question_embedding = get_embedding(question)
    matches = search_similar(question_embedding, limit=top_k)

    context_parts = []
    for i, match in enumerate(matches, start=1):
        context_parts.append(
            f"[Kaynak {i}] source={match['source']} chunk={match['chunk_index']}\n{match['content']}"
        )

    return {
        "matches": matches,
        "context": "\n\n".join(context_parts),
    }


def ask_question(question: str, top_k: int = 3) -> dict[str, Any]:
    retrieved = retrieve_context(question, top_k=top_k)
    matches = retrieved["matches"]

    context_blocks = []
    for i, match in enumerate(matches, start=1):
        context_blocks.append(
            f"[SOURCE {i}]\n"
            f"source={match['source']}\n"
            f"chunk={match['chunk_index']}\n"
            f"text={match['content']}"
        )

    context = "\n\n---\n\n".join(context_blocks)

    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict RAG assistant. "
                "Answer ONLY from the provided context. "
                "If the answer is explicitly written in the context, state it directly. "
                "Do NOT say the information is missing if it appears in the context. "
                "If multiple sources are provided, prefer the most direct source. "
                "Keep the answer short and precise. "
                "At the end, write: Sources: <source names>."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"Context:\n{context}\n\n"
                "Now answer the question using only the context."
            ),
        },
    ]

    response = client.chat.completions.create(
        model=OLLAMA_CHAT_MODEL,
        messages=messages,
        temperature=0.0,
    )

    answer = response.choices[0].message.content or ""

    return {
        "question": question,
        "answer": answer,
        "retrieved_chunks": matches,
    }


def seed_demo_documents() -> dict[str, Any]:
    demo_docs = [
        {
            "source": "demo_architecture_1",
            "text": (
                "The Retrieval API queries the vector database over the PG Wire Protocol. "
                "The vector database stores embeddings and metadata for RAG retrieval."
            ),
        },
        {
            "source": "demo_architecture_2",
            "text": (
                "The AI Orchestrator / Agent API should perform retrieval first, then send the "
                "retrieved context to the language model. The model itself does not directly query "
                "the vector database."
            ),
        },
        {
            "source": "demo_architecture_3",
            "text": (
                "A deployed vLLM server can be replaced by an external LLM provider such as OpenAI, "
                "Anthropic, OpenRouter, or by a local Ollama instance, as long as the application "
                "still controls retrieval and prompt construction."
            ),
        },
        {
            "source": "demo_architecture_4",
            "text": (
                "The Embedding Service generates vectors from text chunks and writes them to the "
                "vector database. Those vectors are later used for similarity search."
            ),
        },
    ]

    added = []
    for doc in demo_docs:
        result = ingest_document(
            source=doc["source"],
            text=doc["text"],
            chunk_size=500,
            overlap=50,
        )
        added.append(result)

    return {
        "message": "Demo dokümanları vector database'e eklendi.",
        "items": added,
    }