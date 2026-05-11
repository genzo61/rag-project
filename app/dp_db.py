from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Sequence, cast

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

from .db import search_similar
from .dp_knowledge_seed import SOURCE as DP_KNOWLEDGE_SOURCE
from .dp_schema import all_allowed_tables, build_sql_schema_prompt, domain_tables
from .embeddings import get_embedding
from .mock_product_schema import has_mock_product_schema
from .rag import PRIMARY_LLM_MODEL, _build_model_candidates, client

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)
logger = logging.getLogger("rag.dp_db")

READ_ONLY_SQL_TIMEOUT_MS = 4000
MAX_SQL_LIMIT = 50
SQL_GENERATOR_MAX_TOKENS = 320
SQL_GUIDANCE_TOP_K = 6
SQL_GUIDANCE_CHAR_LIMIT = 4000

READ_ONLY_SQL_SYSTEM_PROMPT = """You generate PostgreSQL queries for a Data Processing application.

Return strict JSON with keys:
- sql: string
- rationale: short string

Rules:
- Output exactly one read-only PostgreSQL statement.
- The SQL must be SELECT or WITH ... SELECT only.
- Never use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, MERGE, COPY, CALL, DO, or VACUUM.
- Use only the tables and columns listed in the schema section.
- Prefer explicit column lists, stable ORDER BY, and a LIMIT.
- If the question asks for "latest", use the relevant timestamp or descending id with LIMIT 1.
- If the question asks for counts, return a COUNT(*) column with a clear alias.
- If the question cannot be answered from the provided schema alone, return {"sql":"", "rationale":"not answerable from current schema"}.
- If the retrieved guidance says the current schema does not store the requested history or KPI, return {"sql":"", "rationale":"not answerable from current schema"}.
- Do not invent table aliases. Every alias referenced in SELECT, WHERE, GROUP BY, or ORDER BY must also appear in a FROM or JOIN clause.
- Do not use markdown fences.
"""


def _connection(readonly: bool = False):
    conn = psycopg2.connect(
        host=os.getenv("DP_DB_HOST", "localhost"),
        port=int(os.getenv("DP_DB_PORT", "5433")),
        dbname=os.getenv("DP_DB_NAME", "demo_local"),
        user=os.getenv("DP_DB_USER", "demo_user"),
        password=os.getenv("DP_DB_PASSWORD", ""),
    )
    if readonly:
        conn.set_session(readonly=True, autocommit=False)
    return conn


def _fetch_rows(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with _connection(readonly=True) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SET LOCAL statement_timeout = {READ_ONLY_SQL_TIMEOUT_MS}")
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _question_has_any(question: str, tokens: Sequence[str]) -> bool:
    q = (question or "").lower()
    return any(token in q for token in tokens)


def _question_asks_for_count(question: str) -> bool:
    q = _normalize_internal_domain_typos(question)
    return any(
        token in q
        for token in (
            "kac tane",
            "kaç tane",
            "kac adet",
            "kaç adet",
            "sayisi kac",
            "sayısı kaç",
            "count",
            "how many",
            "ne kadar var",
            "mevcut",
        )
    )


def _normalize_internal_domain_typos(question: str) -> str:
    q = (question or "").lower()
    replacements = {
        "aggregiation": "aggregation",
        "aggrigation": "aggregation",
        "aggregration": "aggregation",
        "agregation": "aggregation",
        "aggreagation": "aggregation",
        "validiation": "validation",
        "formulla": "formula",
    }
    for wrong, correct in replacements.items():
        q = q.replace(wrong, correct)
    return q


def _extract_json_object(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except Exception:
        pass

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None

    try:
        return json.loads(match.group(0))
    except Exception:
        return None


def _extract_sql_candidate_from_text(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if not raw:
        return "", ""

    cleaned = raw.replace("```sql", "```").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        cleaned = cleaned[3:-3].strip()

    rationale = ""
    rationale_match = re.search(r"(?im)^rationale\s*:\s*(.+)$", cleaned)
    if rationale_match:
        rationale = rationale_match.group(1).strip()
        cleaned = re.sub(r"(?im)^rationale\s*:\s*.+$", "", cleaned).strip()

    sql_match = re.search(r"(?is)\b(select|with)\b.*", cleaned)
    if not sql_match:
        return "", rationale

    return sql_match.group(0).strip(), rationale


def _extract_named_entity_before_keywords(question: str, keywords: Sequence[str]) -> str | None:
    q = (question or "").strip()

    quoted = re.search(r"['\"]([^'\"]+)['\"]", q)
    if quoted:
        return quoted.group(1).strip()

    for keyword in keywords:
        pattern = rf"([a-zA-Z0-9_.-]+)\s+{re.escape(keyword)}"
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def _extract_phrase_before_keywords(question: str, keywords: Sequence[str]) -> str | None:
    q = (question or "").strip()

    quoted = re.search(r"['\"]([^'\"]+)['\"]", q)
    if quoted:
        return quoted.group(1).strip()

    for keyword in keywords:
        pattern = (
            rf"([a-zA-Z0-9_.-]+(?:\s+[a-zA-Z0-9_.-]+){{0,2}})"
            rf"\s+{re.escape(keyword)}[a-zA-ZçğıöşüÇĞİÖŞÜ]*"
        )
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    return None


def _extract_contains_name_filter(question: str) -> str | None:
    q = question or ""
    patterns = (
        r"adi\s+([a-zA-Z0-9_.-]+)\s+gecen",
        r"adı\s+([a-zA-Z0-9_.-]+)\s+geçen",
        r"name\s+contains\s+([a-zA-Z0-9_.-]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, q, re.IGNORECASE)
        if match:
            return match.group(1).strip()
    return None


def _extract_interval_filter(question: str) -> tuple[int, str] | None:
    q = (question or "").lower()

    minute_match = re.search(r"(\d+)\s*(?:dk|dakika|minute)", q)
    if minute_match:
        return int(minute_match.group(1)), "minute"

    hour_match = re.search(r"(\d+)\s*(?:saat|hour)", q)
    if hour_match:
        return int(hour_match.group(1)), "hour"

    day_match = re.search(r"(\d+)\s*(?:gun|gün|day)", q)
    if day_match:
        return int(day_match.group(1)), "day"

    return None


def _interval_unit_candidates(unit: str) -> tuple[str, ...]:
    normalized = (unit or "").strip().lower()
    if normalized == "minute":
        return ("minute", "minutes")
    if normalized == "hour":
        return ("hour", "hours")
    if normalized == "day":
        return ("day", "days")
    return (normalized,)


def _extract_package_name(question: str) -> str | None:
    known = re.search(
        r"(@[a-z0-9_.-]+/[a-z0-9_.-]+|left-pad|leftpad|is-number|event-stream|lodash|react|express|axios)",
        question or "",
        re.IGNORECASE,
    )
    if known:
        value = known.group(1).lower()
        if value == "leftpad":
            return "left-pad"
        return value

    quoted = re.search(r"['\"]([^'\"]+)['\"]", question or "")
    if quoted:
        value = quoted.group(1).strip().lower()
        if value == "leftpad":
            return "left-pad"
        return value

    return None


def _normalize_product_metric_text(text: str) -> str:
    value = (text or "").lower()
    replacements = str.maketrans(
        {
            "ç": "c",
            "ğ": "g",
            "ı": "i",
            "ö": "o",
            "ş": "s",
            "ü": "u",
        }
    )
    return value.translate(replacements)


def _extract_product_measurement_name(question: str) -> str | None:
    q = _normalize_product_metric_text(_normalize_internal_domain_typos(question))
    metric_aliases: list[tuple[str, tuple[str, ...]]] = [
        (
            "pressure",
            (
                "pressure",
                "basinc",
                "hat basinci",
                "su basinci",
                "sebeke basinci",
                "hattaki basinc",
                "bar degeri",
            ),
        ),
        (
            "flow",
            (
                "flow",
                "debi",
                "akis",
                "akis miktari",
                "su akisi",
                "su debisi",
                "debi miktari",
                "inlet flow",
            ),
        ),
        (
            "level",
            (
                "level",
                "seviye",
                "su seviyesi",
                "depo seviyesi",
                "rezervuar seviyesi",
                "tank seviyesi",
            ),
        ),
        (
            "consumption",
            (
                "consumption",
                "tuketim",
                "su tuketimi",
                "kullanim",
                "faturali tuketim",
                "tuketim miktari",
            ),
        ),
        (
            "leakage",
            (
                "leakage",
                "kacak",
                "su kacagi",
                "sebeke kacagi",
                "kayip",
                "kacak miktari",
            ),
        ),
    ]
    for canonical_name, aliases in metric_aliases:
        if any(alias in q for alias in aliases):
            return canonical_name
    return None


def _extract_product_location_hint(question: str) -> str | None:
    for keywords in (
        ("district", "ilce", "ilçe"),
        ("region", "bolge", "bölge"),
        ("dma",),
        ("reservoir", "rezervuar"),
        ("operation area", "operasyon alani", "operasyon alanı"),
        ("icin", "için"),
    ):
        value = _extract_phrase_before_keywords(question, keywords)
        if value:
            return value
    return None


def _is_npm_question(question: str) -> bool:
    q = _normalize_internal_domain_typos(question)
    return any(
        token in q
        for token in (
            "npm",
            "package",
            "left-pad",
            "leftpad",
            "lodash",
            "event-stream",
            "is-number",
            "quarantine",
            "advisory",
            "cve",
            "hidden metadata",
            "processing failure",
        )
    )


def _is_aggregation_question(question: str) -> bool:
    q = _normalize_internal_domain_typos(question)
    return any(
        token in q
        for token in (
            "aggregation",
            "aggregation run",
            "aggregation runs",
            "aggregation rule",
            "aggregated",
            "processed count",
            "inserted count",
            "run status",
            "audit data",
            "audit trail",
            "window start",
            "window end",
            "aggregationrunaudit",
            "aktif aggregation",
            "basarisiz aggregation",
            "başarısız aggregation",
            "failed olan",
            "1 saatlik",
            "30 dk",
            "30 dakika",
        )
    )


def _is_validation_question(question: str) -> bool:
    q = _normalize_internal_domain_typos(question)
    return any(
        token in q
        for token in (
            "validation",
            "validation rule",
            "validation rules",
            "validation variable",
            "bulk validation",
        )
    )


def _is_formula_question(question: str) -> bool:
    q = _normalize_internal_domain_typos(question)
    return any(
        token in q
        for token in (
            "formula",
            "formulas",
            "calculation",
            "calculations",
            "formula variable",
            "formula variables",
            "snapshot",
            "bulk formula",
            "formul",
            "formulun",
            "formüller",
            "formuller",
        )
    )


def _is_product_question(question: str) -> bool:
    if not has_mock_product_schema():
        return False

    q = _normalize_internal_domain_typos(question)
    if _extract_product_measurement_name(question):
        return True

    return any(
        token in q
        for token in (
            "asset",
            "assets",
            "register",
            "measurement type",
            "measurement point",
            "district",
            "districtinfo",
            "region",
            "operation area",
            "operationarea",
            "water balance",
            "consumer profile",
            "facility type",
            "facility",
            "reservoir",
            "dma",
            "pressure",
            "flow",
            "level",
            "leakage",
            "consumption",
            "s_data",
            "s_data_current",
            "basinc",
            "basınç",
            "debi",
            "akis",
            "akış",
            "seviye",
            "su seviyesi",
            "su basinci",
            "su basıncı",
            "kullanim",
            "kullanım",
            "ilce",
            "ilçe",
            "bolge",
            "bölge",
            "operasyon alani",
            "operasyon alanı",
            "su dengesi",
            "rezervuar",
            "kacak",
            "kaçak",
            "kayip",
            "kayıp",
            "tuketim",
            "tüketim",
        )
    )


def _detect_sql_domains(question: str) -> list[str]:
    domains: list[str] = []
    if _is_formula_question(question):
        domains.append("formula")
    if _is_validation_question(question):
        domains.append("validation")
    if _is_aggregation_question(question):
        domains.append("aggregation")
    if _is_product_question(question):
        domains.append("product")
    return domains


def detect_internal_data_domains(question: str) -> list[str]:
    return _detect_sql_domains(question)


def _prefer_template_query(question: str) -> bool:
    q = _normalize_internal_domain_typos(question)
    template_signals = (
        "kaç",
        "kac",
        "how many",
        "latest",
        "recent",
        "en son",
        "son ",
        "failed",
        "başarısız",
        "basarisiz",
        "hangi datapoint",
        "datapoint",
        "snapshot",
        "bulk formula",
        "bulk validation",
        "aggregation result",
        "result kayıt",
        "result kayit",
        "rule",
        "mapping",
    )
    return any(token in q for token in template_signals)


def _extract_table_names_from_sql(sql: str) -> list[str]:
    matches = re.findall(
        r"(?i)\b(?:from|join)\s+(?:public\.)?([a-z_][a-z0-9_]*)\b",
        sql,
    )
    ordered: list[str] = []
    seen: set[str] = set()
    for match in matches:
        table_name = match.lower()
        if table_name not in seen:
            seen.add(table_name)
            ordered.append(table_name)
    return ordered


def _apply_limit_guard(sql: str, requested_limit: int) -> str:
    normalized_limit = max(1, min(requested_limit, MAX_SQL_LIMIT))
    stripped = sql.rstrip().rstrip(";").strip()
    limit_match = re.search(r"(?i)\blimit\s+(\d+)\b", stripped)
    if not limit_match:
        return f"{stripped}\nLIMIT {normalized_limit}"

    current_limit = int(limit_match.group(1))
    safe_limit = min(current_limit, normalized_limit, MAX_SQL_LIMIT)
    return re.sub(r"(?i)\blimit\s+\d+\b", f"LIMIT {safe_limit}", stripped, count=1)


def _extract_declared_sql_aliases(sql: str) -> set[str]:
    aliases: set[str] = set()
    for table_name, alias in re.findall(
        r"(?i)\b(?:from|join)\s+(?:public\.)?([a-z_][a-z0-9_]*)(?:\s+(?:as\s+)?([a-z_][a-z0-9_]*))?",
        sql,
    ):
        if table_name:
            aliases.add(table_name.lower())
        if alias:
            aliases.add(alias.lower())
    return aliases


def _extract_referenced_sql_aliases(sql: str) -> set[str]:
    aliases = {alias.lower() for alias in re.findall(r"\b([a-z_][a-z0-9_]*)\.", sql)}
    aliases.discard("public")
    return aliases


def _score_sql_guidance_match(content: str, similarity: float, domains: Sequence[str], question: str) -> float:
    text = (content or "").lower()
    score = similarity
    for domain in domains:
        if domain in text:
            score += 0.08
    for keyword in ("join", "columns", "table", "sql", "pattern", "relationship", "business meaning"):
        if keyword in text:
            score += 0.02
    for token in re.findall(r"[a-z_]+", (question or "").lower()):
        if len(token) >= 4 and token in text:
            score += 0.005
    return score


def _retrieve_sql_generation_guidance(question: str, domains: Sequence[str], top_k: int = SQL_GUIDANCE_TOP_K) -> dict[str, Any]:
    retrieval_query = (
        f"{question}\n"
        f"Need schema, table names, column meanings, joins, units, KPI definitions, and example SQL patterns "
        f"for domains: {', '.join(domains)}"
    )
    try:
        query_embedding = get_embedding(retrieval_query)
        raw_matches = search_similar(
            query_embedding=query_embedding,
            limit=max(top_k * 3, 10),
            source=DP_KNOWLEDGE_SOURCE,
        )
    except Exception as exc:
        logger.warning("dp_sql_guidance_retrieval_failed error=%s", exc)
        return {"matches": [], "context": "", "error": str(exc)}

    scored_matches: list[dict[str, Any]] = []
    seen_chunks: set[int] = set()
    for match in raw_matches:
        chunk_index = int(match.get("chunk_index") or 0)
        if chunk_index in seen_chunks:
            continue
        seen_chunks.add(chunk_index)
        score = _score_sql_guidance_match(
            content=str(match.get("content") or ""),
            similarity=float(match.get("similarity") or 0.0),
            domains=domains,
            question=question,
        )
        scored_matches.append(
            {
                "chunk_index": chunk_index,
                "content": str(match.get("content") or ""),
                "similarity": float(match.get("similarity") or 0.0),
                "score": score,
            }
        )

    scored_matches.sort(key=lambda item: item["score"], reverse=True)
    selected = scored_matches[:top_k]

    context_parts: list[str] = []
    current_length = 0
    for index, match in enumerate(selected, start=1):
        snippet = f"[RAG GUIDANCE {index}]\nchunk_index={match['chunk_index']}\ntext={match['content']}"
        if current_length + len(snippet) > SQL_GUIDANCE_CHAR_LIMIT and context_parts:
            break
        context_parts.append(snippet)
        current_length += len(snippet)

    return {
        "matches": selected,
        "context": "\n\n---\n\n".join(context_parts),
    }


def _validate_read_only_sql(sql: str, domains: Sequence[str], requested_limit: int) -> tuple[bool, str | None, str]:
    stripped = (sql or "").strip()
    if not stripped:
        return False, "Generated SQL was empty.", ""

    if "```" in stripped or "--" in stripped or "/*" in stripped:
        return False, "Comments or markdown are not allowed in generated SQL.", ""

    if stripped.count(";") > 1 or (";" in stripped[:-1]):
        return False, "Only one SQL statement is allowed.", ""

    lowered = stripped.lower()
    if not (lowered.startswith("select ") or lowered.startswith("with ")):
        return False, "Only SELECT statements are allowed.", ""

    forbidden_pattern = re.compile(
        r"(?i)\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|merge|copy|call|do|vacuum|analyze|refresh)\b"
    )
    forbidden = forbidden_pattern.search(stripped)
    if forbidden:
        return False, f"Forbidden SQL keyword detected: {forbidden.group(1)}", ""

    allowed_for_request = set(domain_tables(domains))
    globally_allowed = all_allowed_tables()
    used_tables = _extract_table_names_from_sql(stripped)
    if not used_tables:
        return False, "Generated SQL did not reference any allowlisted table.", ""

    for table_name in used_tables:
        if table_name not in globally_allowed:
            return False, f"Table is not in the allowlist: {table_name}", ""
        if table_name not in allowed_for_request:
            return False, f"Table is outside the allowed domains for this question: {table_name}", ""

    declared_aliases = _extract_declared_sql_aliases(stripped)
    referenced_aliases = _extract_referenced_sql_aliases(stripped)
    unknown_aliases = sorted(alias for alias in referenced_aliases if alias not in declared_aliases)
    if unknown_aliases:
        return False, f"Referenced SQL alias was not declared in FROM/JOIN: {', '.join(unknown_aliases)}", ""

    return True, None, _apply_limit_guard(stripped, requested_limit)


def _generate_read_only_sql(question: str, domains: Sequence[str], limit: int) -> dict[str, Any]:
    schema_prompt = build_sql_schema_prompt(domains)
    guidance = _retrieve_sql_generation_guidance(question, domains)
    q = (question or "").lower()
    guidance_text = str(guidance.get("context") or "").lower()
    if (
        any(token in q for token in ("most often", "most frequently", "most used", "en cok", "en çok"))
        and "validation" in domains
        and (
            "does not contain that history" in guidance_text
            or "does not store validation trigger frequency" in guidance_text
            or "cannot be determined from the current internal tables alone" in guidance_text
        )
    ):
        return {
            "ok": True,
            "model_used": "rag_not_answerable_guard",
            "sql": "",
            "rationale": "not answerable from current schema",
            "raw_content": "",
            "rag_guidance": guidance.get("context", ""),
            "rag_guidance_matches": guidance.get("matches", []),
        }
    last_error: Exception | None = None

    messages = [
        {"role": "system", "content": READ_ONLY_SQL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"Relevant domains: {', '.join(domains)}\n"
                f"Preferred max row limit: {max(1, min(limit, MAX_SQL_LIMIT))}\n\n"
                f"Retrieved RAG schema guidance:\n{guidance.get('context') or 'No schema guidance retrieved.'}\n\n"
                f"Schema:\n{schema_prompt}"
            ),
        },
    ]

    for model_name in _build_model_candidates():
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=cast(Any, messages),
                temperature=0.0,
                max_tokens=SQL_GENERATOR_MAX_TOKENS,
            )
            content = response.choices[0].message.content or ""
            parsed = _extract_json_object(content)
            if not parsed:
                sql, rationale = _extract_sql_candidate_from_text(content)
                if not sql:
                    raise ValueError(f"Invalid SQL generator JSON: {content}")
                return {
                    "ok": True,
                    "model_used": model_name,
                    "sql": sql,
                    "rationale": rationale,
                    "raw_content": content,
                    "rag_guidance": guidance.get("context", ""),
                    "rag_guidance_matches": guidance.get("matches", []),
                }

            sql = str(parsed.get("sql") or "").strip()
            rationale = str(parsed.get("rationale") or "").strip()
            return {
                "ok": True,
                "model_used": model_name,
                "sql": sql,
                "rationale": rationale,
                "raw_content": content,
                "rag_guidance": guidance.get("context", ""),
                "rag_guidance_matches": guidance.get("matches", []),
            }
        except Exception as exc:
            last_error = exc
            logger.warning("dp_sql_generator_failed model=%s error=%s", model_name, exc)

    return {
        "ok": False,
        "model_used": PRIMARY_LLM_MODEL,
        "sql": "",
        "rationale": "",
        "error": str(last_error) if last_error else "unknown sql generator error",
        "rag_guidance": guidance.get("context", ""),
        "rag_guidance_matches": guidance.get("matches", []),
    }


def _execute_read_only_sql(sql: str) -> list[dict[str, Any]]:
    with _connection(readonly=True) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(f"SET LOCAL statement_timeout = {READ_ONLY_SQL_TIMEOUT_MS}")
            cur.execute(sql)
            return [dict(row) for row in cur.fetchall()]


def _query_npm_data(question: str, limit: int = 12) -> dict[str, Any]:
    package_name = _extract_package_name(question)
    package_like = f"%{package_name}%" if package_name else None

    sql = """
    SELECT
        p.name AS package_name,
        v.version,
        v.integrity_hash,
        j.status AS processing_status,
        j.started_at,
        j.completed_at,
        f.failure_code,
        f.failure_message,
        vr.result AS validation_result,
        vr.rule_name AS validation_rule,
        hm.key AS metadata_key,
        hm.value AS metadata_value,
        cr.ref_type,
        cr.ref_value,
        ah.action AS audit_action,
        ah.actor AS audit_actor,
        ah.created_at AS audit_created_at
    FROM npm_package p
    LEFT JOIN npm_package_version v ON v.package_id = p.id
    LEFT JOIN npm_processing_job j ON j.package_version_id = v.id
    LEFT JOIN npm_processing_failure f ON f.job_id = j.id
    LEFT JOIN npm_validation_result vr ON vr.job_id = j.id
    LEFT JOIN npm_hidden_metadata hm ON hm.package_version_id = v.id
    LEFT JOIN npm_package_cross_reference cr ON cr.package_id = p.id
    LEFT JOIN npm_processing_audit_history ah ON ah.job_id = j.id
    WHERE (
        %s IS NULL
        OR lower(p.name) = lower(%s)
        OR lower(p.name) LIKE lower(%s)
    )
    ORDER BY ah.created_at DESC NULLS LAST, p.name, v.version
    LIMIT %s
    """

    rows = _fetch_rows(sql, (package_name, package_name, package_like, limit))
    return {
        "ok": True,
        "domain": "npm",
        "package_filter": package_name,
        "query_mode": "template_sql",
        "rows": rows,
    }


def _query_product_data(question: str, limit: int = 12) -> dict[str, Any]:
    measurement_name = _extract_product_measurement_name(question)
    location_hint = _extract_product_location_hint(question)
    location_like = f"%{location_hint}%" if location_hint else None

    if _question_asks_for_count(question) and _question_has_any(
        question,
        ("asset", "assets", "facility", "facilities", "tesis"),
    ):
        sql = """
        SELECT COUNT(*) AS asset_count
        FROM assets a
        LEFT JOIN districtInfo di ON di.id = a.district
        LEFT JOIN region r ON r.id = a.region
        LEFT JOIN operationArea oa ON oa.opAreaId = a.opAreaId
        WHERE (
            %s IS NULL
            OR lower(coalesce(di.name, '')) LIKE lower(%s)
            OR lower(coalesce(r.name, '')) LIKE lower(%s)
            OR lower(coalesce(a.label, '')) LIKE lower(%s)
            OR lower(coalesce(oa.name, '')) LIKE lower(%s)
        )
        """
        rows = _fetch_rows(
            sql,
            (location_hint, location_like, location_like, location_like, location_like),
        )
        return {"ok": True, "domain": "product", "query_mode": "template_sql", "rows": rows}

    if measurement_name and _question_has_any(
        question,
        ("ortalama", "average", "avg"),
    ):
        sql = """
        SELECT
            mt.name AS measurement_name,
            AVG(sd.value) AS avg_value,
            dd.unit,
            COUNT(*) AS sample_count
        FROM s_data sd
        JOIN dataDefinition dd ON dd.register = sd.dataid
        JOIN measurementType mt ON mt.id = dd.measurementTypeId
        JOIN assets a ON a.id = dd.assetId
        LEFT JOIN districtInfo di ON di.id = a.district
        LEFT JOIN region r ON r.id = a.region
        LEFT JOIN operationArea oa ON oa.opAreaId = a.opAreaId
        WHERE lower(mt.name) = lower(%s)
          AND (
              %s IS NULL
              OR lower(coalesce(di.name, '')) LIKE lower(%s)
              OR lower(coalesce(r.name, '')) LIKE lower(%s)
              OR lower(coalesce(a.label, '')) LIKE lower(%s)
              OR lower(coalesce(oa.name, '')) LIKE lower(%s)
          )
        GROUP BY mt.name, dd.unit
        ORDER BY sample_count DESC, mt.name
        LIMIT 1
        """
        rows = _fetch_rows(
            sql,
            (
                measurement_name,
                location_hint,
                location_like,
                location_like,
                location_like,
                location_like,
            ),
        )
        return {"ok": True, "domain": "product", "query_mode": "template_sql", "rows": rows}

    if measurement_name and _question_has_any(
        question,
        (
            "latest",
            "en son",
            "guncel",
            "güncel",
            "current",
            "son deger",
            "son değer",
            "degeri nedir",
            "değeri nedir",
            "miktari nedir",
            "miktarı nedir",
            "nedir",
        ),
    ):
        sql = """
        SELECT
            a.label AS asset_label,
            di.name AS district_name,
            r.name AS region_name,
            mt.name AS measurement_name,
            dd.unit,
            sdc.value AS latest_value,
            sdc.ze1 AS latest_at
        FROM s_data_current sdc
        JOIN dataDefinition dd ON dd.register = sdc.dataid
        JOIN measurementType mt ON mt.id = dd.measurementTypeId
        JOIN assets a ON a.id = dd.assetId
        LEFT JOIN districtInfo di ON di.id = a.district
        LEFT JOIN region r ON r.id = a.region
        LEFT JOIN operationArea oa ON oa.opAreaId = a.opAreaId
        WHERE lower(mt.name) = lower(%s)
          AND (
              %s IS NULL
              OR lower(coalesce(di.name, '')) LIKE lower(%s)
              OR lower(coalesce(r.name, '')) LIKE lower(%s)
              OR lower(coalesce(a.label, '')) LIKE lower(%s)
              OR lower(coalesce(oa.name, '')) LIKE lower(%s)
          )
        ORDER BY sdc.ze1 DESC NULLS LAST, a.id
        LIMIT %s
        """
        rows = _fetch_rows(
            sql,
            (
                measurement_name,
                location_hint,
                location_like,
                location_like,
                location_like,
                location_like,
                limit,
            ),
        )
        return {"ok": True, "domain": "product", "query_mode": "template_sql", "rows": rows}

    if (
        _question_has_any(question, ("olmayan", "without", "no active"))
        and _question_has_any(
            question,
            (
                "datadefinition",
                "data definition",
                "active register",
                "aktif register",
                "aktif tanim",
                "aktif tanım",
            ),
        )
    ):
        sql = """
        SELECT
            a.id AS asset_id,
            a.label AS asset_label,
            a.type AS asset_type
        FROM assets a
        LEFT JOIN dataDefinition dd
            ON dd.assetId = a.id
           AND coalesce(dd.isActive, false) = true
        WHERE dd.id IS NULL
        ORDER BY a.id
        LIMIT %s
        """
        rows = _fetch_rows(sql, (limit,))
        return {"ok": True, "domain": "product", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(
        question,
        ("water balance", "su dengesi", "billing input", "bill metered", "system input"),
    ):
        sql = """
        SELECT
            a.label AS asset_label,
            wb.interval,
            dd_in.label AS system_input_label,
            dd_metered.label AS bill_metered_label,
            dd_unmetered.label AS bill_unmetered_label,
            wb.leakageNetwork,
            wb.leakageReservoir,
            wb.leakageService
        FROM waterBalance wb
        JOIN assets a ON a.id = wb.assetId
        LEFT JOIN dataDefinition dd_in ON dd_in.id = wb.systemInputId
        LEFT JOIN dataDefinition dd_metered ON dd_metered.id = wb.billMeteredId
        LEFT JOIN dataDefinition dd_unmetered ON dd_unmetered.id = wb.billUnmeteredId
        ORDER BY wb.recordDate DESC NULLS LAST, wb.id DESC
        LIMIT %s
        """
        rows = _fetch_rows(sql, (limit,))
        return {"ok": True, "domain": "product", "query_mode": "template_sql", "rows": rows}

    return {"ok": False, "domain": "product", "query_mode": "template_sql", "rows": []}


def _query_aggregation_data(question: str, limit: int = 12) -> dict[str, Any]:
    interval_filter = _extract_interval_filter(question)

    if _question_asks_for_count(question) and _question_has_any(
        question,
        ("aggregation", "aggregiation", "aggregation rule", "aggregiation rule", "rule"),
    ):
        sql = """
        SELECT COUNT(*) AS aggregation_rule_count
        FROM aggregation_rule
        """
        if _question_has_any(question, ("aktif", "enabled")):
            sql += " WHERE enabled = true"
        rows = _fetch_rows(sql, ())
        return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(
        question,
        (
            "aggregation result",
            "aggregation results",
            "result kayit",
            "result kayıt",
            "son aggregation result",
            "latest aggregation result",
            "recent aggregation result",
            "persisted output",
            "persisted outputs",
        ),
    ):
        sql = """
        SELECT
            ar.id AS rule_id,
            ar.name AS rule_name,
            agr.value,
            agr.time,
            agr.agg_type,
            agr.quality,
            agr.source_count,
            agr.interval
        FROM aggregation_rule ar
        JOIN aggregation_result agr ON agr.rule_id = ar.id
        ORDER BY agr.time DESC NULLS LAST, agr.id DESC
        LIMIT %s
        """
        rows = _fetch_rows(sql, (limit,))
        return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(
        question,
        (
            "en son calisan",
            "en son çalışan",
            "son calisan",
            "son çalışan",
            "latest run",
            "most recent run",
            "latest aggregation run",
            "most recent aggregation run",
        ),
    ):
        sql = """
        SELECT
            ar.id AS rule_id,
            ar.name AS rule_name,
            ara.started_at,
            ara.completed_at,
            ara.status,
            ara.processed_count,
            ara.inserted_count,
            ara.message
        FROM aggregation_rule ar
        JOIN aggregation_run_audit ara ON ara.rule_id = ar.id
        ORDER BY ara.started_at DESC NULLS LAST, ara.id DESC
        LIMIT 1
        """
        rows = _fetch_rows(sql, ())
        return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(question, ("basarisiz", "başarısız", "failed", "status'u failed")):
        sql = """
        SELECT
            ar.id AS rule_id,
            ar.name AS rule_name,
            ara.window_start,
            ara.window_end,
            ara.started_at,
            ara.completed_at,
            ara.status,
            ara.processed_count,
            ara.inserted_count,
            ara.message
        FROM aggregation_rule ar
        JOIN aggregation_run_audit ara ON ara.rule_id = ar.id
        WHERE upper(coalesce(ara.status, '')) = 'FAILED'
        ORDER BY ara.started_at DESC NULLS LAST, ara.id DESC
        LIMIT %s
        """
        rows = _fetch_rows(sql, (limit,))
        return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(question, ("average method", "average method kullanan", "method kullanan")):
        sql = """
        SELECT
            ar.id AS rule_id,
            ar.name AS rule_name,
            ar.interval_value,
            ar.interval_unit,
            ar.method,
            ar.enabled,
            ar.last_calculated_at
        FROM aggregation_rule ar
        WHERE lower(coalesce(ar.method, '')) = 'average'
        ORDER BY ar.id
        LIMIT %s
        """
        rows = _fetch_rows(sql, (limit,))
        return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}

    if interval_filter:
        unit_candidates = _interval_unit_candidates(interval_filter[1])
        sql = """
        SELECT
            ar.id AS rule_id,
            ar.name AS rule_name,
            ar.interval_value,
            ar.interval_unit,
            ar.method,
            ar.gap_filling_mode,
            ar.enabled,
            ar.last_calculated_at
        FROM aggregation_rule ar
        WHERE ar.interval_value = %s
          AND lower(ar.interval_unit) = ANY(%s)
        ORDER BY ar.id
        LIMIT %s
        """
        rows = _fetch_rows(sql, (interval_filter[0], list(unit_candidates), limit))
        return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}

    sql = """
    SELECT
        ar.id AS rule_id,
        ar.name AS rule_name,
        ar.interval_value,
        ar.interval_unit,
        ar.method,
        ar.gap_filling_mode,
        ar.enabled,
        ar.last_calculated_at,
        ara.window_start,
        ara.window_end,
        ara.started_at,
        ara.completed_at,
        ara.status,
        ara.processed_count,
        ara.inserted_count,
        ara.message
    FROM aggregation_rule ar
    LEFT JOIN aggregation_run_audit ara ON ara.rule_id = ar.id
    ORDER BY ara.started_at DESC NULLS LAST, ar.id
    LIMIT %s
    """
    rows = _fetch_rows(sql, (limit,))
    return {"ok": True, "domain": "aggregation", "query_mode": "template_sql", "rows": rows}


def _query_validation_data(question: str, limit: int = 20) -> dict[str, Any]:
    q = (question or "").lower()

    if _question_asks_for_count(question) and _question_has_any(
        question,
        ("validation", "validation rule", "validation kural", "kural"),
    ):
        rows = _fetch_rows("SELECT COUNT(*) AS validation_rule_count FROM validation_rule", ())
        return {"ok": True, "domain": "validation", "query_mode": "template_sql", "rows": rows}

    if "most often" in q or "most frequently" in q or "most used" in q:
        return {
            "ok": True,
            "domain": "validation",
            "query_mode": "template_sql",
            "rows": [
                {
                    "note": (
                        "The current Data Processing DB schema defines validation rules and mappings, "
                        "but it does not store validation trigger-frequency history. "
                        "A most-often-used validation rule cannot be determined from the current internal tables alone."
                    )
                }
            ],
        }

    sql = """
    SELECT
        vr.id AS validation_rule_id,
        vr.name AS validation_rule_name,
        vr.rule_text,
        vv.variable_name,
        vv.datapoint_id,
        bvr.id AS bulk_validation_rule_id,
        bvr.name AS bulk_validation_rule_name,
        bvg.group_key,
        bvg.group_name,
        bvgm.variable_name AS group_variable_name,
        bvgm.datapoint_id AS group_datapoint_id
    FROM validation_rule vr
    LEFT JOIN validation_variable vv ON vv.validation_rule_id = vr.id
    LEFT JOIN bulk_validation_group bvg ON bvg.validation_rule_id = vr.id
    LEFT JOIN bulk_validation_rule bvr ON bvr.id = bvg.bulk_validation_rule_id
    LEFT JOIN bulk_validation_group_mapping bvgm ON bvgm.group_id = bvg.id
    ORDER BY vr.id, vv.variable_name, bvr.id, bvg.group_key
    LIMIT %s
    """
    rows = _fetch_rows(sql, (limit,))
    return {"ok": True, "domain": "validation", "query_mode": "template_sql", "rows": rows}


def _query_formula_data(question: str, limit: int = 20) -> dict[str, Any]:
    formula_name = _extract_named_entity_before_keywords(question, ("formulu", "formulunun", "formula", "formul"))
    name_contains = _extract_contains_name_filter(question)

    if _question_has_any(
        question,
        ("kac tane", "kaç tane", "kaç formula", "kaç formül", "sistemde kaç tane formula", "how many"),
    ):
        rows = _fetch_rows("SELECT COUNT(*) AS formula_count FROM formula", ())
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(question, ("en son olusturulan", "en son oluşturulan", "son olusturulan", "son oluşturulan", "latest formula")):
        sql = """
        SELECT
            f.id AS formula_id,
            f.name AS formula_name,
            f.formula_text
        FROM formula f
        ORDER BY f.id DESC
        LIMIT 1
        """
        rows = _fetch_rows(sql, ())
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(question, ("bulk formula", "bulk olarak", "bulk formula olarak")):
        sql = """
        WITH selected_bulk_formulas AS (
            SELECT
                bf.id,
                bf.name
            FROM bulk_formula bf
            ORDER BY bf.id
            LIMIT %s
        )
        SELECT
            sbf.id AS bulk_formula_id,
            sbf.name AS bulk_formula_name,
            bfg.group_key,
            bfg.group_name,
            bfg.result_data_id,
            bfgm.variable_name AS group_variable_name,
            bfgm.datapoint_id AS group_datapoint_id
        FROM selected_bulk_formulas sbf
        LEFT JOIN bulk_formula_group bfg ON bfg.bulk_formula_id = sbf.id
        LEFT JOIN bulk_formula_group_mapping bfgm ON bfgm.group_id = bfg.id
        ORDER BY sbf.id, bfg.group_key, bfgm.variable_name
        """
        rows = _fetch_rows(sql, (limit,))
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if name_contains:
        sql = """
        SELECT
            f.id AS formula_id,
            f.name AS formula_name,
            f.formula_text
        FROM formula f
        WHERE lower(f.name) LIKE lower(%s)
        ORDER BY f.id
        LIMIT %s
        """
        rows = _fetch_rows(sql, (f"%{name_contains}%", limit))
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if formula_name and _question_has_any(question, ("hangi datapoint", "datapointlere bagli", "datapointlere bağlı", "bagli", "bağlı")):
        sql = """
        SELECT
            f.id AS formula_id,
            f.name AS formula_name,
            fv.variable_name,
            fv.datapoint_id
        FROM formula f
        LEFT JOIN formula_variable fv ON fv.formula_id = f.id
        WHERE lower(f.name) = lower(%s)
        ORDER BY fv.variable_name
        LIMIT %s
        """
        rows = _fetch_rows(sql, (formula_name, limit))
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if formula_name and _question_has_any(question, ("formula text", "formula text'i", "formula texti", "formula_text", "text'i ne", "texti ne")):
        sql = """
        SELECT
            f.id AS formula_id,
            f.name AS formula_name,
            f.formula_text
        FROM formula f
        WHERE lower(f.name) = lower(%s)
        LIMIT 1
        """
        rows = _fetch_rows(sql, (formula_name,))
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if formula_name and _question_has_any(question, ("en son hesaplanan sonucu", "son hesaplanan sonucu", "sonuc var mi", "sonuç var mı", "snapshot")):
        sql = """
        SELECT
            f.id AS formula_id,
            f.name AS formula_name,
            frs.chart_data_id,
            frs.result_value,
            frs.computed_at
        FROM formula f
        LEFT JOIN formula_result_snapshot frs ON frs.formula_id = f.id
        WHERE lower(f.name) = lower(%s)
        ORDER BY frs.computed_at DESC NULLS LAST
        LIMIT 1
        """
        rows = _fetch_rows(sql, (formula_name,))
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    if _question_has_any(question, ("en cok variable", "en çok variable", "most variables")):
        sql = """
        SELECT
            f.id AS formula_id,
            f.name AS formula_name,
            COUNT(fv.id) AS variable_count
        FROM formula f
        LEFT JOIN formula_variable fv ON fv.formula_id = f.id
        GROUP BY f.id, f.name
        ORDER BY variable_count DESC, f.id DESC
        LIMIT 1
        """
        rows = _fetch_rows(sql, ())
        return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}

    sql = """
    SELECT
        f.id AS formula_id,
        f.name AS formula_name,
        f.formula_text,
        fv.variable_name,
        fv.datapoint_id,
        frs.chart_data_id,
        frs.result_value,
        frs.computed_at,
        bf.id AS bulk_formula_id,
        bf.name AS bulk_formula_name,
        bfg.group_key,
        bfg.group_name,
        bfg.result_data_id,
        bfgm.variable_name AS group_variable_name,
        bfgm.datapoint_id AS group_datapoint_id
    FROM formula f
    LEFT JOIN formula_variable fv ON fv.formula_id = f.id
    LEFT JOIN formula_result_snapshot frs ON frs.formula_id = f.id
    LEFT JOIN bulk_formula_group bfg ON bfg.formula_id = f.id
    LEFT JOIN bulk_formula bf ON bf.id = bfg.bulk_formula_id
    LEFT JOIN bulk_formula_group_mapping bfgm ON bfgm.group_id = bfg.id
    ORDER BY f.id, fv.variable_name, frs.computed_at DESC NULLS LAST
    LIMIT %s
    """
    rows = _fetch_rows(sql, (limit,))
    return {"ok": True, "domain": "formula", "query_mode": "template_sql", "rows": rows}


def _query_internal_data_via_safe_sql(question: str, limit: int = 12) -> dict[str, Any] | None:
    domains = _detect_sql_domains(question)
    if not domains:
        return None

    generated = _generate_read_only_sql(question, domains, limit)
    if not generated.get("ok"):
        return {
            "ok": False,
            "domain": "+".join(domains),
            "query_mode": "generated_read_only_sql",
            "rows": [],
            "error": generated.get("error", "sql generation failed"),
        }

    sql = str(generated.get("sql") or "")
    is_valid, error, safe_sql = _validate_read_only_sql(sql, domains, limit)
    if not is_valid:
        return {
            "ok": False,
            "domain": "+".join(domains),
            "query_mode": "generated_read_only_sql",
            "rows": [],
            "error": error,
            "generated_sql": sql,
            "sql_generator_model": generated.get("model_used"),
        }

    try:
        rows = _execute_read_only_sql(safe_sql)
    except Exception as exc:
        return {
            "ok": False,
            "domain": "+".join(domains),
            "query_mode": "generated_read_only_sql",
            "rows": [],
            "error": str(exc),
            "generated_sql": safe_sql,
            "sql_generator_model": generated.get("model_used"),
        }

    return {
        "ok": True,
        "domain": "+".join(domains),
        "query_mode": "generated_read_only_sql",
        "rows": rows,
        "sql": safe_sql,
        "tables": _extract_table_names_from_sql(safe_sql),
        "rationale": generated.get("rationale", ""),
        "sql_generator_model": generated.get("model_used"),
        "rag_guidance": generated.get("rag_guidance", ""),
        "rag_guidance_matches": generated.get("rag_guidance_matches", []),
    }


def inspect_sql_generation_path(question: str, limit: int = 12, execute_sql: bool = False) -> dict[str, Any]:
    domains = _detect_sql_domains(question)
    if not domains:
        return {
            "ok": False,
            "question": question,
            "domains": [],
            "error": "No internal Data Processing DB domain detected for this question.",
        }

    generated = _generate_read_only_sql(question, domains, limit)
    sql = str(generated.get("sql") or "")
    is_valid, validation_error, safe_sql = _validate_read_only_sql(sql, domains, limit)

    result: dict[str, Any] = {
        "ok": bool(generated.get("ok")),
        "question": question,
        "domains": domains,
        "model_used": generated.get("model_used"),
        "rationale": generated.get("rationale", ""),
        "sql": sql,
        "is_valid": is_valid,
        "validation_error": validation_error,
        "safe_sql": safe_sql,
        "tables": _extract_table_names_from_sql(safe_sql or sql),
        "rag_guidance": generated.get("rag_guidance", ""),
        "rag_guidance_matches": generated.get("rag_guidance_matches", []),
    }

    if not generated.get("ok"):
        result["error"] = generated.get("error", "sql generation failed")
        return result

    if execute_sql and is_valid:
        try:
            rows = _execute_read_only_sql(safe_sql)
            result["execution_ok"] = True
            result["row_count"] = len(rows)
            result["rows"] = rows
        except Exception as exc:
            result["execution_ok"] = False
            result["execution_error"] = str(exc)
    else:
        result["execution_ok"] = False

    return result


def query_internal_data(question: str, limit: int = 12) -> dict[str, Any]:
    try:
        if _is_npm_question(question):
            return _query_npm_data(question, limit)

        if _is_product_question(question):
            product_result = _query_product_data(question, limit)
            if product_result.get("ok"):
                return product_result

        if _prefer_template_query(question):
            if _is_aggregation_question(question):
                return _query_aggregation_data(question, limit)

            if _is_formula_question(question):
                return _query_formula_data(question, limit)

            if _is_validation_question(question):
                return _query_validation_data(question, limit)

        generated_result = _query_internal_data_via_safe_sql(question, limit)
        if generated_result and generated_result.get("ok"):
            return generated_result

        if _is_aggregation_question(question):
            return _query_aggregation_data(question, limit)

        if _is_formula_question(question):
            return _query_formula_data(question, limit)

        if _is_validation_question(question):
            return _query_validation_data(question, limit)

        if generated_result and not generated_result.get("ok"):
            return generated_result

        return {
            "ok": True,
            "domain": "generic",
            "query_mode": "note",
            "rows": [
                {
                    "note": (
                        "No specialized Data Processing DB query branch matched this question. "
                        "Use Vector DB for architecture-level answers, or ask for a specific aggregation, "
                        "validation, formula, audit, snapshot, or package-processing record."
                    )
                }
            ],
        }
    except Exception as exc:
        logger.exception("dp_db_query_failed")
        return {
            "ok": False,
            "error": str(exc),
            "rows": [],
        }


def _format_dp_row(row: dict[str, Any], index: int, label: str) -> str:
    if row.get("note") and len(row) == 1:
        return f"[{label} NOTE {index}]\n{row['note']}"

    parts = [f"[{label} ROW {index}]"]
    for key, value in row.items():
        parts.append(f"{key}={value}")
    return "\n".join(parts)


def build_dp_db_context(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        error_text = result.get("error") or "unknown error"
        generated_sql = result.get("generated_sql")
        if generated_sql:
            return f"DP DB query failed: {error_text}\nGenerated SQL was rejected: {generated_sql}"
        return f"DP DB query failed: {error_text}"

    rows = result.get("rows", [])
    if not rows:
        if result.get("query_mode") == "generated_read_only_sql":
            tables = ", ".join(result.get("tables", []))
            return f"DP DB read-only SQL returned no matching rows. tables={tables}"
        return "DP DB returned no matching internal rows."

    label = "DP DB"
    domain = str(result.get("domain") or "").lower()
    if "formula" in domain:
        label = "FORMULA"
    elif "validation" in domain:
        label = "VALIDATION"
    elif "aggregation" in domain:
        label = "AGGREGATION"
    elif "product" in domain:
        label = "PRODUCT"
    elif "npm" in domain:
        label = "NPM"

    header_parts: list[str] = []
    query_mode = result.get("query_mode")
    if query_mode == "generated_read_only_sql":
        header_parts.append("[DP DB QUERY MODE]")
        header_parts.append("mode=generated_read_only_sql")
        if result.get("tables"):
            header_parts.append("tables=" + ",".join(result["tables"]))
        if result.get("rationale"):
            header_parts.append("rationale=" + str(result["rationale"]))

    body = "\n\n---\n\n".join(
        _format_dp_row(row, index, label)
        for index, row in enumerate(rows, start=1)
    )

    if not header_parts:
        return body

    return "\n".join(header_parts) + "\n\n---\n\n" + body
