import os
import logging
from pathlib import Path
from time import perf_counter
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv

logger = logging.getLogger("rag.db")
load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT"))
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
VECTOR_DIM = int(os.getenv("VECTOR_DIM"))


def normalize_source(source: str) -> str:
    value = (source or "").strip()

    if value.lower().endswith(".pdf"):
        value = Path(value).stem

    return value.lower().strip()


def get_connection():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def vector_to_pgvector_str(vector: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.8f}" for x in vector) + "]"


def init_db() -> None:
    create_table_sql = f"""
    CREATE EXTENSION IF NOT EXISTS vector;

    CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        source TEXT NOT NULL,
        page_start INTEGER,
        page_end INTEGER,
        chunk_index INTEGER NOT NULL DEFAULT 0,
        content TEXT NOT NULL,
        embedding vector({VECTOR_DIM}) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (source, page_start, page_end, chunk_index)
    );

    CREATE INDEX IF NOT EXISTS idx_documents_source
    ON documents (source);

    CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
    ON documents
    USING hnsw (embedding vector_cosine_ops);
    """

    start = perf_counter()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_table_sql)
        conn.commit()

    logger.info("init_db completed in %.1f ms", (perf_counter() - start) * 1000)


def insert_document(
    source: str,
    page_start: int | None,
    page_end: int | None,
    chunk_index: int,
    content: str,
    embedding: list[float],
) -> None:
    source = normalize_source(source)
    embedding_str = vector_to_pgvector_str(embedding)

    sql = """
    INSERT INTO documents (source, page_start, page_end, chunk_index, content, embedding)
    VALUES (%s, %s, %s, %s, %s, %s::vector)
    ON CONFLICT (source, page_start, page_end, chunk_index)
    DO UPDATE SET
        content = EXCLUDED.content,
        embedding = EXCLUDED.embedding;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                sql,
                (source, page_start, page_end, chunk_index, content, embedding_str),
            )
        conn.commit()

def insert_documents_batch(items: list[dict[str, Any]]) -> None:
    if not items:
        return

    rows = []
    for item in items:
        rows.append(
            (
                normalize_source(item["source"]),
                item["page_start"],
                item["page_end"],
                item["chunk_index"],
                item["content"],
                vector_to_pgvector_str(item["embedding"]),
            )
        )

    sql = """
    INSERT INTO documents (source, page_start, page_end, chunk_index, content, embedding)
    VALUES %s
    ON CONFLICT (source, page_start, page_end, chunk_index)
    DO UPDATE SET
        content = EXCLUDED.content,
        embedding = EXCLUDED.embedding;
    """

    start = perf_counter()
    with get_connection() as conn:
        with conn.cursor() as cur:
            execute_values(
                cur,
                sql,
                rows,
                template="(%s, %s, %s, %s, %s, %s::vector)",
                page_size=100,
            )
        conn.commit()

    logger.info(
        "insert_documents_batch inserted=%d in %.1f ms",
        len(rows),
        (perf_counter() - start) * 1000,
    )   
    
def search_similar(query_embedding: list[float], limit: int = 3, source: str | None = None) -> list[dict[str, Any]]:
    embedding_str = vector_to_pgvector_str(query_embedding)

    if source:
        source = normalize_source(source)

    params: tuple[Any, ...]
    if source:
        sql = """
        SELECT
            id,
            source,
            page_start,
            page_end,
            chunk_index,
            content,
            1 - (embedding <=> %s::vector) AS similarity
        FROM documents
        WHERE source = %s
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
        """
        params = (embedding_str, source, embedding_str, limit)
    else:
        sql = """
    SELECT
        id,
        source,
        page_start,
        page_end,
        chunk_index,
        content,
        1 - (embedding <=> %s::vector) AS similarity
    FROM documents
    ORDER BY embedding <=> %s::vector
    LIMIT %s;
    """
        params = (embedding_str, embedding_str, limit)

    start = perf_counter()
    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    duration_ms = (perf_counter() - start) * 1000
    logger.info(
        "search_similar limit=%d rows=%d in %.1f ms",
        limit,
        len(rows),
        duration_ms,
    )
    return [dict(row) for row in rows]


def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    sql = """
    SELECT
        id,
        source,
        page_start,
        page_end,
        chunk_index,
        LEFT(content, 180) AS preview,
        created_at
    FROM documents
    ORDER BY source, page_start, chunk_index
    LIMIT %s;
    """

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (limit,))
            rows = cur.fetchall()
            return [dict(row) for row in rows]
def list_sources() -> list[str]:
    sql = """
    SELECT DISTINCT source
    FROM documents
    ORDER BY source;
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            return [row[0] for row in rows]

def count_documents() -> int:
    sql = "SELECT COUNT(*) FROM documents;"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            return int(cur.fetchone()[0])


def delete_by_source(source: str) -> int:
    normalized = normalize_source(source)

    sql = """
    DELETE FROM documents
    WHERE lower(source) = lower(%s)
       OR lower(source) = lower(%s);
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (normalized, normalized + ".pdf"))
            deleted = cur.rowcount
        conn.commit()
        return deleted


def delete_all_documents() -> int:
    sql = "DELETE FROM documents;"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            deleted = cur.rowcount
        conn.commit()
        return deleted
