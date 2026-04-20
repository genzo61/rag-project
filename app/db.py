import os
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

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
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(create_table_sql)
        conn.commit()


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


def search_similar(query_embedding: list[float], limit: int = 3) -> list[dict[str, Any]]:
    embedding_str = vector_to_pgvector_str(query_embedding)

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

    with get_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, (embedding_str, embedding_str, limit))
            rows = cur.fetchall()
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