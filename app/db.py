import os
import logging
import re
from pathlib import Path
from time import perf_counter
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
from dotenv import load_dotenv

logger = logging.getLogger("rag.db")
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

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


def _resolve_runtime_vector_dim() -> int:
    configured_dim = VECTOR_DIM

    try:
        from .embeddings import get_embedding

        runtime_dim = len(get_embedding("vector dimension probe"))
        if configured_dim and configured_dim != runtime_dim:
            logger.warning(
                "VECTOR_DIM mismatch configured=%d runtime=%d; runtime dimension will be used for schema checks",
                configured_dim,
                runtime_dim,
            )
        return runtime_dim
    except Exception as exc:
        if configured_dim:
            logger.warning(
                "Could not probe runtime embedding dimension; falling back to configured VECTOR_DIM=%d error=%s",
                configured_dim,
                exc,
            )
            return configured_dim
        raise RuntimeError(
            "Unable to determine vector dimension from configuration or embedding backend."
        ) from exc


def _documents_table_exists(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.documents')")
        row = cur.fetchone()
        return bool(row and row[0])


def _documents_embedding_dim(conn) -> int | None:
    sql = """
    SELECT format_type(a.atttypid, a.atttypmod)
    FROM pg_attribute a
    JOIN pg_class c ON c.oid = a.attrelid
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'documents'
      AND a.attname = 'embedding'
      AND NOT a.attisdropped;
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        if not row or not row[0]:
            return None
        match = re.search(r"vector\((\d+)\)", str(row[0]))
        if not match:
            return None
        return int(match.group(1))


def _documents_row_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM documents;")
        return int(cur.fetchone()[0])


def _create_documents_schema(conn, vector_dim: int) -> None:
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS documents (
        id SERIAL PRIMARY KEY,
        source TEXT NOT NULL,
        page_start INTEGER,
        page_end INTEGER,
        chunk_index INTEGER NOT NULL DEFAULT 0,
        content TEXT NOT NULL,
        embedding vector({vector_dim}) NOT NULL,
        created_at TIMESTAMP DEFAULT NOW(),
        UNIQUE (source, page_start, page_end, chunk_index)
    );

    CREATE INDEX IF NOT EXISTS idx_documents_source
    ON documents (source);

    CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
    ON documents
    USING hnsw (embedding vector_cosine_ops);
    """
    with conn.cursor() as cur:
        cur.execute(create_table_sql)


def _ensure_documents_schema(conn, vector_dim: int) -> None:
    with conn.cursor() as cur:
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    if not _documents_table_exists(conn):
        _create_documents_schema(conn, vector_dim)
        return

    current_dim = _documents_embedding_dim(conn)
    if current_dim is None or current_dim == vector_dim:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_source
                ON documents (source);
                """
            )
            cur.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
                ON documents
                USING hnsw (embedding vector_cosine_ops);
                """
            )
        return

    row_count = _documents_row_count(conn)
    if row_count > 0:
        raise RuntimeError(
            "documents.embedding dimension mismatch: "
            f"database={current_dim}, embedding_backend={vector_dim}. "
            "Clear and re-ingest the vector documents, or align the embedding model and VECTOR_DIM."
        )

    with conn.cursor() as cur:
        cur.execute("DROP INDEX IF EXISTS idx_documents_embedding_hnsw;")
        cur.execute(
            f"ALTER TABLE documents ALTER COLUMN embedding TYPE vector({vector_dim});"
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_source
            ON documents (source);
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_documents_embedding_hnsw
            ON documents
            USING hnsw (embedding vector_cosine_ops);
            """
        )


def _validate_embedding_dimension(expected_dim: int, actual_dim: int, operation: str) -> None:
    if expected_dim != actual_dim:
        raise RuntimeError(
            f"{operation} dimension mismatch: database expects {expected_dim}, but embedding/query has {actual_dim}. "
            "Align VECTOR_DIM and the embedding model, or recreate the vector data with the current embedding model."
        )


def init_db() -> None:
    vector_dim = _resolve_runtime_vector_dim()
    start = perf_counter()
    with get_connection() as conn:
        _ensure_documents_schema(conn, vector_dim)
        conn.commit()

    logger.info(
        "init_db completed vector_dim=%d in %.1f ms",
        vector_dim,
        (perf_counter() - start) * 1000,
    )


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

    first_embedding = items[0].get("embedding") or []
    embedding_dim = len(first_embedding)
    if not embedding_dim:
        raise ValueError("insert_documents_batch received an empty embedding.")

    rows = []
    for item in items:
        item_embedding = item["embedding"]
        if len(item_embedding) != embedding_dim:
            raise ValueError("insert_documents_batch received mixed embedding dimensions.")
        rows.append(
            (
                normalize_source(item["source"]),
                item["page_start"],
                item["page_end"],
                item["chunk_index"],
                item["content"],
                vector_to_pgvector_str(item_embedding),
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
        db_dim = _documents_embedding_dim(conn)
        if db_dim is not None:
            _validate_embedding_dimension(db_dim, embedding_dim, "insert_documents_batch")
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
    query_dim = len(query_embedding)

    if source:
        source = normalize_source(source)

    documents_sql = """
    SELECT
        id,
        source,
        page_start,
        page_end,
        chunk_index,
        content,
        1 - (embedding <=> %s::vector) AS similarity
    FROM documents
    WHERE (%s::text IS NULL OR lower(source) = lower(%s::text) OR lower(source) = lower(%s::text || '.pdf'))
    ORDER BY embedding <=> %s::vector
    LIMIT %s;
    """

    start = perf_counter()
    with get_connection() as conn:
        db_dim = _documents_embedding_dim(conn)
        if db_dim is not None:
            _validate_embedding_dimension(db_dim, query_dim, "search_similar")
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                documents_sql,
                (embedding_str, source, source, source, embedding_str, limit),
            )
            rows = cur.fetchall()

            if rows:
                duration_ms = (perf_counter() - start) * 1000
                logger.info(
                    "search_similar backend=documents limit=%d rows=%d source=%s in %.1f ms",
                    limit,
                    len(rows),
                    source,
                    duration_ms,
                )
                return [dict(row) for row in rows]

            cur.execute("SELECT to_regclass('public.document_chunk')")
            table_ref = cur.fetchone()
            table_exists = bool(table_ref and next(iter(table_ref.values()), None))
            if not table_exists:
                duration_ms = (perf_counter() - start) * 1000
                logger.info(
                    "search_similar backend=documents fallback=document_chunk_missing limit=%d rows=0 source=%s in %.1f ms",
                    limit,
                    source,
                    duration_ms,
                )
                return []

            source_expr = "COALESCE(vmetadata->>'source', vmetadata->>'file_name', vmetadata->>'filename', collection_name)"
            chunk_sql = f"""
            SELECT
                id,
                {source_expr} AS source,
                CASE
                    WHEN (vmetadata->>'page') ~ '^\\d+$' THEN (vmetadata->>'page')::int
                    ELSE 1
                END AS page_start,
                CASE
                    WHEN (vmetadata->>'page') ~ '^\\d+$' THEN (vmetadata->>'page')::int
                    ELSE 1
                END AS page_end,
                0 AS chunk_index,
                text AS content,
                1 - (vector <=> %s::vector) AS similarity
            FROM document_chunk
            WHERE (
                %s::text IS NULL
                OR lower({source_expr}) = lower(%s::text)
                OR lower({source_expr}) = lower(%s::text || '.pdf')
            )
            ORDER BY vector <=> %s::vector
            LIMIT %s;
            """
            cur.execute(
                chunk_sql,
                (embedding_str, source, source, source, embedding_str, limit),
            )
            rows = cur.fetchall()

    duration_ms = (perf_counter() - start) * 1000
    logger.info(
        "search_similar backend=document_chunk limit=%d rows=%d source=%s in %.1f ms",
        limit,
        len(rows),
        source,
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
    documents_sql = "SELECT COUNT(*) FROM documents;"
    chunk_sql = "SELECT COUNT(*) FROM document_chunk;"
    table_check_sql = "SELECT to_regclass('public.document_chunk');"

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(documents_sql)
            documents_count = int(cur.fetchone()[0])
            if documents_count > 0:
                return documents_count

            cur.execute(table_check_sql)
            table_ref = cur.fetchone()
            if not table_ref or not table_ref[0]:
                return 0

            cur.execute(chunk_sql)
            chunk_count = int(cur.fetchone()[0])
            return chunk_count


def count_documents_by_source(source: str) -> int:
    normalized = normalize_source(source)

    sql = """
    SELECT COUNT(*)
    FROM documents
    WHERE lower(source) = lower(%s)
       OR lower(source) = lower(%s);
    """

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (normalized, normalized + ".pdf"))
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
