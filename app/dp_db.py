import os
import re
import logging
from pathlib import Path
from typing import Any

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)
logger = logging.getLogger("rag.dp_db")


def _connection():
    return psycopg2.connect(
        host=os.getenv("DP_DB_HOST", "localhost"),
        port=int(os.getenv("DP_DB_PORT", "5433")),
        dbname=os.getenv("DP_DB_NAME", "demo_local"),
        user=os.getenv("DP_DB_USER", "demo_user"),
        password=os.getenv("DP_DB_PASSWORD", ""),
    )


def _fetch_rows(sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with _connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]


def _question_has_any(question: str, tokens: tuple[str, ...]) -> bool:
    q = (question or "").lower()
    return any(token in q for token in tokens)


def _extract_named_entity_before_keywords(question: str, keywords: tuple[str, ...]) -> str | None:
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


def _extract_contains_name_filter(question: str) -> str | None:
    q = question or ""
    match = re.search(r"adı\s+([a-zA-Z0-9_.-]+)\s+geçen", q, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def _extract_interval_filter(question: str) -> tuple[int, str] | None:
    q = (question or "").lower()

    minute_match = re.search(r"(\d+)\s*(?:dk|dakika)", q)
    if minute_match:
        return int(minute_match.group(1)), "minute"

    hour_match = re.search(r"(\d+)\s*saat", q)
    if hour_match:
        return int(hour_match.group(1)), "hour"

    return None


def _extract_datapoint_filter(question: str) -> str | None:
    q = question or ""

    quoted = re.search(r"datapoint[^\w]*['\"]([^'\"]+)['\"]", q, re.IGNORECASE)
    if quoted:
        return quoted.group(1).strip()

    around = re.search(r"([a-zA-Z0-9_.-]+)\s+datapoint", q, re.IGNORECASE)
    if around:
        return around.group(1).strip()

    explicit = re.search(r"datapoint[^\w]*([a-zA-Z0-9_.-]+)", q, re.IGNORECASE)
    if explicit:
        return explicit.group(1).strip()

    return None


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


def _is_npm_question(question: str) -> bool:
    q = (question or "").lower()
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
    q = (question or "").lower()
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
            "başarısız aggregation",
            "failed olan",
            "1 saatlik",
            "30 dk",
            "30 dakika",
        )
    )


def _is_validation_question(question: str) -> bool:
    q = (question or "").lower()
    return any(
        token in q
        for token in (
            "validation",
            "validation rule",
            "validation rules",
            "validation variable",
            "bulk validation",
            "datapoint",
            "datapoints",
        )
    )


def _is_formula_question(question: str) -> bool:
    q = (question or "").lower()
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
            "formülü",
            "formül",
            "formüller",
        )
    )


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
        "rows": rows,
    }


def _query_aggregation_data(question: str, limit: int = 12) -> dict[str, Any]:
    q = (question or "").lower()
    interval_filter = _extract_interval_filter(question)

    if _question_has_any(question, ("kaç tane", "sayısı kaç", "kaç aggregation")):
        sql = """
        SELECT COUNT(*) AS aggregation_rule_count
        FROM aggregation_rule
        """
        if _question_has_any(question, ("aktif", "enabled")):
            sql += " WHERE enabled = true"
        rows = _fetch_rows(sql, ())
        return {
            "ok": True,
            "domain": "aggregation",
            "rows": rows,
        }

    if _question_has_any(question, ("en son çalışan", "son çalışan", "latest run", "most recent run")):
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
        return {
            "ok": True,
            "domain": "aggregation",
            "rows": rows,
        }

    if _question_has_any(question, ("başarısız", "failed", "status'u failed")):
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
        return {
            "ok": True,
            "domain": "aggregation",
            "rows": rows,
        }

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
        return {
            "ok": True,
            "domain": "aggregation",
            "rows": rows,
        }

    if interval_filter:
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
          AND lower(ar.interval_unit) = lower(%s)
        ORDER BY ar.id
        LIMIT %s
        """
        rows = _fetch_rows(sql, (interval_filter[0], interval_filter[1], limit))
        return {
            "ok": True,
            "domain": "aggregation",
            "rows": rows,
        }

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
    return {
        "ok": True,
        "domain": "aggregation",
        "rows": rows,
    }


def _query_validation_data(question: str, limit: int = 20) -> dict[str, Any]:
    q = (question or "").lower()

    if "most often" in q or "most frequently" in q or "most used" in q:
        return {
            "ok": True,
            "domain": "validation",
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
    return {
        "ok": True,
        "domain": "validation",
        "rows": rows,
    }


def _query_formula_data(question: str, limit: int = 20) -> dict[str, Any]:
    formula_name = _extract_named_entity_before_keywords(question, ("formülü", "formülünün", "formula", "formul"))
    name_contains = _extract_contains_name_filter(question)

    if _question_has_any(question, ("kaç tane", "kaç formula", "kaç formül", "sistemde kaç tane formula")):
        sql = "SELECT COUNT(*) AS formula_count FROM formula"
        rows = _fetch_rows(sql, ())
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

    if _question_has_any(question, ("en son oluşturulan", "son oluşturulan", "latest formula")):
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
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

    if _question_has_any(question, ("bulk formula", "bulk olarak", "bulk formula olarak")):
        sql = """
        SELECT
            bf.id AS bulk_formula_id,
            bf.name AS bulk_formula_name,
            bfg.group_key,
            bfg.group_name,
            bfg.result_data_id,
            bfgm.variable_name AS group_variable_name,
            bfgm.datapoint_id AS group_datapoint_id
        FROM bulk_formula bf
        LEFT JOIN bulk_formula_group bfg ON bfg.bulk_formula_id = bf.id
        LEFT JOIN bulk_formula_group_mapping bfgm ON bfgm.group_id = bfg.id
        ORDER BY bf.id, bfg.group_key, bfgm.variable_name
        LIMIT %s
        """
        rows = _fetch_rows(sql, (limit,))
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

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
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

    if formula_name and _question_has_any(question, ("hangi datapoint", "datapointlere bağlı", "bağlı", "bagli")):
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
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

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
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

    if formula_name and _question_has_any(question, ("en son hesaplanan sonucu", "son hesaplanan sonucu", "sonuç var mı", "sonuc var mi", "snapshot")):
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
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

    if _question_has_any(question, ("en çok variable", "en cok variable", "most variables")):
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
        return {
            "ok": True,
            "domain": "formula",
            "rows": rows,
        }

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
    return {
        "ok": True,
        "domain": "formula",
        "rows": rows,
    }


def query_internal_data(question: str, limit: int = 12) -> dict[str, Any]:
    try:
        if _is_npm_question(question):
            return _query_npm_data(question, limit)

        if _is_aggregation_question(question):
            return _query_aggregation_data(question, limit)

        if _is_formula_question(question):
            return _query_formula_data(question, limit)

        if _is_validation_question(question):
            return _query_validation_data(question, limit)

        return {
            "ok": True,
            "domain": "generic",
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


def build_dp_db_context(result: dict[str, Any]) -> str:
    if not result.get("ok"):
        return f"DP DB query failed: {result.get('error')}"

    rows = result.get("rows", [])
    domain = result.get("domain", "generic")

    if not rows:
        return "DP DB returned no matching internal rows."

    if domain == "npm":
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

    if domain == "aggregation":
        blocks = []
        for i, row in enumerate(rows, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[AGGREGATION ROW {i}]",
                        f"rule_id={row.get('rule_id')}",
                        f"rule_name={row.get('rule_name')}",
                        f"interval={row.get('interval_value')} {row.get('interval_unit')}",
                        f"method={row.get('method')}",
                        f"gap_filling_mode={row.get('gap_filling_mode')}",
                        f"enabled={row.get('enabled')}",
                        f"last_calculated_at={row.get('last_calculated_at')}",
                        f"window_start={row.get('window_start')}",
                        f"window_end={row.get('window_end')}",
                        f"started_at={row.get('started_at')}",
                        f"completed_at={row.get('completed_at')}",
                        f"status={row.get('status')}",
                        f"processed_count={row.get('processed_count')}",
                        f"inserted_count={row.get('inserted_count')}",
                        f"message={row.get('message')}",
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks)

    if domain == "validation":
        blocks = []
        for i, row in enumerate(rows, start=1):
            if row.get("note"):
                blocks.append(f"[VALIDATION NOTE {i}]\n{row.get('note')}")
                continue
            blocks.append(
                "\n".join(
                    [
                        f"[VALIDATION ROW {i}]",
                        f"validation_rule_id={row.get('validation_rule_id')}",
                        f"validation_rule_name={row.get('validation_rule_name')}",
                        f"rule_text={row.get('rule_text')}",
                        f"variable_name={row.get('variable_name')}",
                        f"datapoint_id={row.get('datapoint_id')}",
                        f"bulk_validation_rule_id={row.get('bulk_validation_rule_id')}",
                        f"bulk_validation_rule_name={row.get('bulk_validation_rule_name')}",
                        f"group_key={row.get('group_key')}",
                        f"group_name={row.get('group_name')}",
                        f"group_variable_name={row.get('group_variable_name')}",
                        f"group_datapoint_id={row.get('group_datapoint_id')}",
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks)

    if domain == "formula":
        blocks = []
        for i, row in enumerate(rows, start=1):
            blocks.append(
                "\n".join(
                    [
                        f"[FORMULA ROW {i}]",
                        f"formula_id={row.get('formula_id')}",
                        f"formula_name={row.get('formula_name')}",
                        f"formula_text={row.get('formula_text')}",
                        f"variable_name={row.get('variable_name')}",
                        f"datapoint_id={row.get('datapoint_id')}",
                        f"chart_data_id={row.get('chart_data_id')}",
                        f"result_value={row.get('result_value')}",
                        f"computed_at={row.get('computed_at')}",
                        f"bulk_formula_id={row.get('bulk_formula_id')}",
                        f"bulk_formula_name={row.get('bulk_formula_name')}",
                        f"group_key={row.get('group_key')}",
                        f"group_name={row.get('group_name')}",
                        f"result_data_id={row.get('result_data_id')}",
                        f"group_variable_name={row.get('group_variable_name')}",
                        f"group_datapoint_id={row.get('group_datapoint_id')}",
                    ]
                )
            )
        return "\n\n---\n\n".join(blocks)

    return "\n\n---\n\n".join(
        f"[DP DB ROW {i}]\n{row.get('note', str(row))}"
        for i, row in enumerate(rows, start=1)
    )
