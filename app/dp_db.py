import os
import re
import logging
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger("rag.dp_db")


def _connection():
    return psycopg2.connect(
        host=os.getenv("DP_DB_HOST", "localhost"),
        port=int(os.getenv("DP_DB_PORT", "5433")),
        dbname=os.getenv("DP_DB_NAME", "demo_local"),
        user=os.getenv("DP_DB_USER", "demo_user"),
        password=os.getenv("DP_DB_PASSWORD", ""),
    )


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



def query_internal_data(question: str, limit: int = 12) -> dict[str, Any]:
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
    LIMIT %s;
    """

    try:
        with _connection() as conn:
            with conn.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute(sql, (package_name, package_name, package_like, limit))
                rows = [dict(row) for row in cur.fetchall()]

        return {
            "ok": True,
            "package_filter": package_name,
            "rows": rows,
        }
    except Exception as exc:
        logger.exception("dp_db_query_failed")
        return {
            "ok": False,
            "package_filter": package_name,
            "error": str(exc),
            "rows": [],
        }


def build_dp_db_context(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"DP DB query failed: {result.get('error')}"

    rows = result.get("rows", [])
    if not rows:
        return "DP DB returned no matching internal rows."

    blocks = []
    for i, row in enumerate(rows, start=1):
        blocks.append(
            "\n".join(
                [
                    f"[DP DB ROW {i}]",
                    f"package={row.get('package_name')}",
                    f"version={row.get('version')}",
                    f"processing_status={row.get('processing_status')}",
                    f"failure_code={row.get('failure_code')}",
                    f"failure_message={row.get('failure_message')}",
                    f"validation_result={row.get('validation_result')}",
                    f"validation_rule={row.get('validation_rule')}",
                    f"metadata={row.get('metadata_key')}:{row.get('metadata_value')}",
                    f"cross_reference={row.get('ref_type')}:{row.get('ref_value')}",
                    f"audit={row.get('audit_action')} by {row.get('audit_actor')} at {row.get('audit_created_at')}",
                ]
            )
        )

    return "\n\n---\n\n".join(blocks)
