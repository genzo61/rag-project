from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import init_db
from app.dp_db import inspect_sql_generation_path
from app.dp_knowledge_seed import seed_dp_assistant_knowledge
from app.dp_schema import build_rag_schema_documents

EVAL_DIR = ROOT / "evaluation"
REPORTS_DIR = ROOT / "reports"
TEST_SET_PATH = EVAL_DIR / "dp_rag_test_cases.json"
RESULTS_PATH = REPORTS_DIR / "dp_rag_eval_results.json"
REPORT_PATH = REPORTS_DIR / "dp_rag_eval_report.md"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def normalize_sql(value: str) -> str:
    return normalize_text((value or "").replace("\n", " ").replace("\t", " "))


def contains_all(text: str, fragments: list[str]) -> list[str]:
    lowered = normalize_text(text)
    return [fragment for fragment in fragments if normalize_text(fragment) not in lowered]


def audit_rag_population() -> list[dict[str, Any]]:
    docs = build_rag_schema_documents()
    combined = normalize_text("\n".join(docs))
    checks = [
        {
            "name": "table_descriptions",
            "required_terms": [
                "schema catalog for table formula",
                "schema catalog for table validation_rule",
                "schema catalog for table aggregation_rule",
            ],
        },
        {
            "name": "column_meanings",
            "required_terms": [
                "result_value",
                "processed_count",
                "inserted_count",
                "source_count",
            ],
        },
        {
            "name": "relationships",
            "required_terms": [
                "formula.id = formula_variable.formula_id",
                "aggregation_rule.id = aggregation_run_audit.rule_id",
                "bulk_validation_group.validation_rule_id = validation_rule.id",
            ],
        },
        {
            "name": "units_and_business_meanings",
            "required_terms": [
                "interval_value",
                "interval_unit",
                "minute, hour, or day",
                "business meanings",
            ],
        },
        {
            "name": "example_sql_patterns",
            "required_terms": [
                "select count(*) as formula_count from formula",
                "select ar.id as rule_id, ar.name as rule_name, ara.started_at",
                "join validation_variable vv on vv.datapoint_id = fv.datapoint_id",
            ],
        },
        {
            "name": "kpi_definitions",
            "required_terms": [
                "formula_count",
                "aggregation_rule_count",
                "latest aggregation run",
            ],
        },
        {
            "name": "known_query_limitations",
            "required_terms": [
                "does not contain that history",
                "not store validation trigger frequency",
                "do not assume aggregation_result still has",
            ],
        },
    ]

    results: list[dict[str, Any]] = []
    for check in checks:
        missing = [term for term in check["required_terms"] if normalize_text(term) not in combined]
        results.append(
            {
                "name": check["name"],
                "ok": not missing,
                "missing_terms": missing,
            }
        )
    return results


def evaluate_case(case: dict[str, Any], execute_sql: bool) -> dict[str, Any]:
    result = inspect_sql_generation_path(
        question=str(case["question"]),
        limit=int(case.get("limit", 12)),
        execute_sql=execute_sql,
    )

    rag_guidance = str(result.get("rag_guidance") or "")
    safe_sql = str(result.get("safe_sql") or result.get("sql") or "")
    domains = list(result.get("domains") or [])
    tables = list(result.get("tables") or [])

    expected_domains = list(case.get("expected_domains") or [])
    required_tables = list(case.get("required_tables") or [])
    forbidden_tables = list(case.get("forbidden_tables") or [])
    required_sql_fragments = list(case.get("required_sql_fragments") or [])
    forbidden_sql_fragments = list(case.get("forbidden_sql_fragments") or [])
    required_context_terms = list(case.get("required_context_terms") or [])

    missing_context_terms = contains_all(rag_guidance, required_context_terms)
    missing_sql_fragments = contains_all(safe_sql, required_sql_fragments)
    present_forbidden_sql_fragments = [
        fragment
        for fragment in forbidden_sql_fragments
        if normalize_text(fragment) in normalize_sql(safe_sql)
    ]
    missing_required_tables = [table for table in required_tables if table not in tables]
    unexpected_tables = [table for table in tables if table in forbidden_tables]
    missing_tables_in_context = [table for table in required_tables if normalize_text(table) not in normalize_text(rag_guidance)]

    domain_ok = set(domains) == set(expected_domains)
    answerable = bool(case.get("answerable", True))
    not_answerable_ok = (not safe_sql.strip()) if not answerable else True

    checks = {
        "domain_ok": domain_ok,
        "rag_context_present": bool(rag_guidance.strip()),
        "required_context_terms_ok": not missing_context_terms,
        "required_tables_ok": not missing_required_tables,
        "required_tables_in_context_ok": not missing_tables_in_context,
        "sql_valid": bool(result.get("is_valid")) if answerable else not_answerable_ok,
        "required_sql_fragments_ok": not missing_sql_fragments if answerable else not_answerable_ok,
        "forbidden_sql_fragments_ok": not present_forbidden_sql_fragments,
        "forbidden_tables_ok": not unexpected_tables,
        "not_answerable_ok": not_answerable_ok,
        "execution_ok": bool(result.get("execution_ok")) if execute_sql and answerable and result.get("is_valid") else True,
    }

    failed_checks = [name for name, ok in checks.items() if not ok]
    if not failed_checks:
        status = "pass"
    elif len(failed_checks) <= 2:
        status = "partial"
    else:
        status = "fail"

    evaluation = {
        "id": case["id"],
        "question": case["question"],
        "status": status,
        "checks": checks,
        "failed_checks": failed_checks,
        "missing_context_terms": missing_context_terms,
        "missing_required_tables": missing_required_tables,
        "missing_tables_in_context": missing_tables_in_context,
        "missing_sql_fragments": missing_sql_fragments,
        "present_forbidden_sql_fragments": present_forbidden_sql_fragments,
        "unexpected_tables": unexpected_tables,
        "domains": domains,
        "tables": tables,
        "rag_guidance_matches": result.get("rag_guidance_matches", []),
        "rag_guidance": rag_guidance,
        "sql": result.get("sql", ""),
        "safe_sql": safe_sql,
        "rationale": result.get("rationale", ""),
        "validation_error": result.get("validation_error"),
        "execution_error": result.get("execution_error"),
        "row_count": result.get("row_count"),
    }
    return evaluation


def build_summary(audit: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = Counter(item["status"] for item in results)
    failed_check_counts = Counter()
    rag_population_gaps: list[str] = []
    sql_accuracy_gaps: list[str] = []
    safety_gaps: list[str] = []

    for item in audit:
        if not item["ok"]:
            rag_population_gaps.extend(item["missing_terms"])

    for result in results:
        failed_check_counts.update(result["failed_checks"])
        rag_population_gaps.extend(result["missing_context_terms"])
        rag_population_gaps.extend(result["missing_tables_in_context"])
        sql_accuracy_gaps.extend(result["missing_required_tables"])
        sql_accuracy_gaps.extend(result["missing_sql_fragments"])
        if result["present_forbidden_sql_fragments"]:
            safety_gaps.extend(result["present_forbidden_sql_fragments"])
        if result["unexpected_tables"]:
            safety_gaps.extend(result["unexpected_tables"])
        if result.get("validation_error"):
            safety_gaps.append(str(result["validation_error"]))
        if result.get("execution_error"):
            safety_gaps.append(str(result["execution_error"]))

    required_improvements: list[str] = []
    if rag_population_gaps:
        required_improvements.append(
            "Add or refine RAG chunks so the retrieved context consistently names the required tables, columns, and business semantics."
        )
    if sql_accuracy_gaps:
        required_improvements.append(
            "Tighten SQL generation prompts or few-shot patterns so the generated SQL uses the expected join path and predicates."
        )
    if safety_gaps:
        required_improvements.append(
            "Strengthen SQL validation and not-answerable handling when the schema lacks the requested KPI or history."
        )

    return {
        "case_counts": dict(status_counts),
        "failed_checks": dict(failed_check_counts),
        "rag_population_gaps": sorted(set(rag_population_gaps)),
        "sql_accuracy_gaps": sorted(set(sql_accuracy_gaps)),
        "safety_gaps": sorted(set(safety_gaps)),
        "required_improvements": required_improvements,
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# DP RAG SQL Evaluation")
    lines.append("")
    lines.append(f"Generated at: {payload['generated_at']}")
    lines.append("")

    lines.append("## RAG Population Audit")
    for item in payload["rag_population_audit"]:
        status = "PASS" if item["ok"] else "FAIL"
        lines.append(f"- {status} `{item['name']}`")
        if item["missing_terms"]:
            lines.append(f"  Missing: {', '.join(item['missing_terms'])}")
    lines.append("")

    summary = payload["summary"]
    lines.append("## Summary")
    lines.append(f"- Pass: {summary['case_counts'].get('pass', 0)}")
    lines.append(f"- Partial: {summary['case_counts'].get('partial', 0)}")
    lines.append(f"- Fail: {summary['case_counts'].get('fail', 0)}")
    if summary["required_improvements"]:
        lines.append("- Required improvements:")
        for item in summary["required_improvements"]:
            lines.append(f"  - {item}")
    lines.append("")

    lines.append("## Cases")
    for case in payload["cases"]:
        lines.append(f"### {case['id']} [{case['status'].upper()}]")
        lines.append(case["question"])
        lines.append("")
        lines.append(f"- Domains: {', '.join(case['domains']) or 'none'}")
        lines.append(f"- Tables: {', '.join(case['tables']) or 'none'}")
        lines.append(f"- Failed checks: {', '.join(case['failed_checks']) or 'none'}")
        if case["validation_error"]:
            lines.append(f"- Validation error: {case['validation_error']}")
        if case["execution_error"]:
            lines.append(f"- Execution error: {case['execution_error']}")
        lines.append("")
        lines.append("SQL:")
        lines.append("```sql")
        lines.append(case["safe_sql"] or case["sql"] or "")
        lines.append("```")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the DP RAG schema and SQL-generation pipeline.")
    parser.add_argument("--execute-sql", action="store_true", help="Execute validated read-only SQL against the configured DP DB.")
    parser.add_argument("--replace-existing", action="store_true", help="Reseed dp-assistant-demo guidance chunks before the run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    init_db()
    seed_dp_assistant_knowledge(replace_existing=args.replace_existing)

    cases = load_json(TEST_SET_PATH)
    audit = audit_rag_population()
    results = [evaluate_case(case, execute_sql=args.execute_sql) for case in cases]
    summary = build_summary(audit, results)

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execute_sql": args.execute_sql,
        "replace_existing": args.replace_existing,
        "rag_population_audit": audit,
        "cases": results,
        "summary": summary,
    }

    save_json(RESULTS_PATH, payload)
    REPORT_PATH.write_text(render_markdown(payload), encoding="utf-8")

    print(f"Wrote {RESULTS_PATH}")
    print(f"Wrote {REPORT_PATH}")
    print(
        "Summary:",
        f"pass={summary['case_counts'].get('pass', 0)}",
        f"partial={summary['case_counts'].get('partial', 0)}",
        f"fail={summary['case_counts'].get('fail', 0)}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
