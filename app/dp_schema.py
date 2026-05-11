from __future__ import annotations

from typing import Any, Sequence


DP_DOMAIN_TABLES: dict[str, list[str]] = {
    "formula": [
        "formula",
        "formula_variable",
        "formula_chart",
        "formula_result_snapshot",
        "bulk_formula",
        "bulk_formula_variable",
        "bulk_formula_group",
        "bulk_formula_group_mapping",
    ],
    "validation": [
        "validation_rule",
        "validation_variable",
        "bulk_validation_rule",
        "bulk_validation_variable",
        "bulk_validation_group",
        "bulk_validation_group_mapping",
    ],
    "aggregation": [
        "aggregation_rule",
        "aggregation_rule_datapoint",
        "aggregation_result",
        "aggregation_run_audit",
    ],
}


DP_SCHEMA_TABLES: dict[str, dict[str, Any]] = {
    "formula": {
        "domain": "formula",
        "description": "Stores formula definitions.",
        "columns": ["id", "name", "formula_text", "created_at", "updated_at"],
        "joins": [
            "formula.id = formula_variable.formula_id",
            "formula.id = formula_chart.formula_id",
            "formula.id = formula_result_snapshot.formula_id",
            "formula.id = bulk_formula_group.formula_id",
        ],
    },
    "formula_variable": {
        "domain": "formula",
        "description": "Maps a formula variable name to a datapoint_id.",
        "columns": ["id", "formula_id", "variable_name", "datapoint_id"],
        "joins": [
            "formula_variable.formula_id = formula.id",
        ],
    },
    "formula_chart": {
        "domain": "formula",
        "description": "Stores chart outputs for a formula.",
        "columns": ["id", "formula_id", "label", "data_id", "chart_color"],
        "joins": [
            "formula_chart.formula_id = formula.id",
            "formula_chart.data_id = formula_result_snapshot.chart_data_id",
        ],
    },
    "formula_result_snapshot": {
        "domain": "formula",
        "description": "Stores the latest persisted result snapshot per formula and chart_data_id.",
        "columns": ["id", "formula_id", "chart_data_id", "result_value", "computed_at", "created_at", "updated_at"],
        "joins": [
            "formula_result_snapshot.formula_id = formula.id",
            "formula_result_snapshot.chart_data_id = formula_chart.data_id",
        ],
    },
    "bulk_formula": {
        "domain": "formula",
        "description": "Stores reusable bulk formula templates.",
        "columns": ["id", "name", "formula_text", "created_at", "updated_at"],
        "joins": [
            "bulk_formula.id = bulk_formula_variable.bulk_formula_id",
            "bulk_formula.id = bulk_formula_group.bulk_formula_id",
        ],
    },
    "bulk_formula_variable": {
        "domain": "formula",
        "description": "Declares ordered variables for a bulk formula template.",
        "columns": ["id", "bulk_formula_id", "variable_name", "sort_order"],
        "joins": [
            "bulk_formula_variable.bulk_formula_id = bulk_formula.id",
        ],
    },
    "bulk_formula_group": {
        "domain": "formula",
        "description": "Stores instantiated bulk-formula groups and the output result_data_id.",
        "columns": ["id", "bulk_formula_id", "group_key", "group_name", "result_data_id", "formula_id", "created_at", "updated_at"],
        "joins": [
            "bulk_formula_group.bulk_formula_id = bulk_formula.id",
            "bulk_formula_group.formula_id = formula.id",
            "bulk_formula_group.id = bulk_formula_group_mapping.group_id",
        ],
    },
    "bulk_formula_group_mapping": {
        "domain": "formula",
        "description": "Maps each bulk-formula group variable to a datapoint_id.",
        "columns": ["id", "group_id", "variable_name", "datapoint_id"],
        "joins": [
            "bulk_formula_group_mapping.group_id = bulk_formula_group.id",
        ],
    },
    "validation_rule": {
        "domain": "validation",
        "description": "Stores validation rule definitions.",
        "columns": ["id", "name", "rule_text", "created_at", "updated_at"],
        "joins": [
            "validation_rule.id = validation_variable.validation_rule_id",
            "validation_rule.id = bulk_validation_group.validation_rule_id",
        ],
    },
    "validation_variable": {
        "domain": "validation",
        "description": "Maps a validation variable name to a datapoint_id.",
        "columns": ["id", "validation_rule_id", "variable_name", "datapoint_id"],
        "joins": [
            "validation_variable.validation_rule_id = validation_rule.id",
        ],
    },
    "bulk_validation_rule": {
        "domain": "validation",
        "description": "Stores reusable bulk validation templates.",
        "columns": ["id", "name", "rule_text", "created_at", "updated_at"],
        "joins": [
            "bulk_validation_rule.id = bulk_validation_variable.bulk_validation_rule_id",
            "bulk_validation_rule.id = bulk_validation_group.bulk_validation_rule_id",
        ],
    },
    "bulk_validation_variable": {
        "domain": "validation",
        "description": "Declares ordered variables for a bulk validation template.",
        "columns": ["id", "bulk_validation_rule_id", "variable_name", "sort_order"],
        "joins": [
            "bulk_validation_variable.bulk_validation_rule_id = bulk_validation_rule.id",
        ],
    },
    "bulk_validation_group": {
        "domain": "validation",
        "description": "Stores instantiated bulk-validation groups and the generated validation_rule_id.",
        "columns": ["id", "bulk_validation_rule_id", "group_key", "group_name", "validation_rule_id", "created_at", "updated_at"],
        "joins": [
            "bulk_validation_group.bulk_validation_rule_id = bulk_validation_rule.id",
            "bulk_validation_group.validation_rule_id = validation_rule.id",
            "bulk_validation_group.id = bulk_validation_group_mapping.group_id",
        ],
    },
    "bulk_validation_group_mapping": {
        "domain": "validation",
        "description": "Maps each bulk-validation group variable to a datapoint_id.",
        "columns": ["id", "group_id", "variable_name", "datapoint_id"],
        "joins": [
            "bulk_validation_group_mapping.group_id = bulk_validation_group.id",
        ],
    },
    "aggregation_rule": {
        "domain": "aggregation",
        "description": "Stores aggregation rules and scheduling metadata.",
        "columns": [
            "id",
            "name",
            "interval_value",
            "interval_unit",
            "method",
            "gap_filling_mode",
            "fixed_value",
            "last_calculated_at",
            "enabled",
            "created_at",
            "updated_at",
        ],
        "joins": [
            "aggregation_rule.id = aggregation_rule_datapoint.rule_id",
            "aggregation_rule.id = aggregation_result.rule_id",
            "aggregation_rule.id = aggregation_run_audit.rule_id",
        ],
    },
    "aggregation_rule_datapoint": {
        "domain": "aggregation",
        "description": "Maps an aggregation rule to source datapoints.",
        "columns": ["id", "rule_id", "data_id"],
        "joins": [
            "aggregation_rule_datapoint.rule_id = aggregation_rule.id",
        ],
    },
    "aggregation_result": {
        "domain": "aggregation",
        "description": "Stores persisted aggregation outputs. Current schema uses time and interval; it does not have data_id, window_start, or window_end anymore.",
        "columns": ["id", "rule_id", "value", "time", "agg_type", "quality", "source_count", "created_at", "interval"],
        "joins": [
            "aggregation_result.rule_id = aggregation_rule.id",
        ],
    },
    "aggregation_run_audit": {
        "domain": "aggregation",
        "description": "Stores audit history for aggregation runs.",
        "columns": [
            "id",
            "rule_id",
            "window_start",
            "window_end",
            "started_at",
            "completed_at",
            "status",
            "processed_count",
            "inserted_count",
            "message",
            "created_at",
        ],
        "joins": [
            "aggregation_run_audit.rule_id = aggregation_rule.id",
        ],
    },
}


def all_allowed_tables() -> set[str]:
    return set(DP_SCHEMA_TABLES)


def domain_tables(domains: Sequence[str] | None = None) -> list[str]:
    if not domains:
        return list(DP_SCHEMA_TABLES)

    seen: set[str] = set()
    ordered: list[str] = []
    for domain in domains:
        for table_name in DP_DOMAIN_TABLES.get(domain, []):
            if table_name not in seen:
                seen.add(table_name)
                ordered.append(table_name)
    return ordered


def build_sql_schema_prompt(domains: Sequence[str] | None = None) -> str:
    lines: list[str] = []
    for table_name in domain_tables(domains):
        table = DP_SCHEMA_TABLES[table_name]
        lines.append(f"TABLE {table_name}")
        lines.append(f"DESCRIPTION: {table['description']}")
        lines.append("COLUMNS: " + ", ".join(table["columns"]))
        if table.get("joins"):
            lines.append("JOINS: " + " | ".join(table["joins"]))
        lines.append("")
    return "\n".join(lines).strip()


def _build_table_catalog_documents() -> list[str]:
    docs: list[str] = []
    for table_name, table in DP_SCHEMA_TABLES.items():
        joins = " | ".join(table.get("joins", [])) or "No documented joins."
        docs.append(
            (
                f"Schema catalog for table {table_name}: domain={table['domain']}. "
                f"Business meaning: {table['description']} "
                f"Columns: {', '.join(table['columns'])}. "
                f"Known joins: {joins}"
            )
        )
    return docs


def _build_semantic_guidance_documents() -> list[str]:
    return [
        (
            "Aggregation units and business meanings: aggregation_rule.interval_value is the numeric size of the schedule or bucket. "
            "aggregation_rule.interval_unit is the unit such as minute, hour, or day. "
            "aggregation_result.interval is the persisted output bucket label or duration text for the stored aggregate row. "
            "aggregation_result.value is the computed numeric aggregate, and aggregation_result.source_count is the number of source datapoints or rows contributing to that aggregate."
        ),
        (
            "Aggregation KPI definitions: aggregation_rule_count means COUNT(*) over aggregation_rule. "
            "The latest aggregation run means the highest aggregation_run_audit.started_at, with aggregation_run_audit.id as a stable tiebreaker. "
            "processed_count is the number of source records handled in one run, and inserted_count is the number of result rows written by that run."
        ),
        (
            "Formula business meanings: formula is the authored formula definition, formula_variable maps variable placeholders to datapoint ids, "
            "formula_chart describes output chart series, and formula_result_snapshot stores the latest persisted computed value. "
            "formula_result_snapshot.result_value is the business value to show to users, and chart_data_id is the output datapoint identifier reused by formula_chart.data_id."
        ),
        (
            "Validation business meanings: validation_rule stores the rule definition text, validation_variable maps rule variables to datapoint ids, "
            "bulk_validation_rule is the reusable template, and bulk_validation_group plus bulk_validation_group_mapping describe instantiated groups. "
            "The current schema supports rule-definition and datapoint-mapping questions, but it does not contain KPI history for how often each validation rule executed."
        ),
        (
            "SQL generation guidance for business questions: for counts use COUNT(*) with a clear alias such as formula_count or aggregation_rule_count. "
            "For latest rows prefer ORDER BY the relevant timestamp DESC NULLS LAST and then a stable id DESC. "
            "For mapping questions start from the parent definition table and join only through the documented foreign-key path."
        ),
    ]


def build_rag_schema_documents() -> list[str]:
    formula_tables = ", ".join(DP_DOMAIN_TABLES["formula"])
    validation_tables = ", ".join(DP_DOMAIN_TABLES["validation"])
    aggregation_tables = ", ".join(DP_DOMAIN_TABLES["aggregation"])

    return [
        *_build_table_catalog_documents(),
        *_build_semantic_guidance_documents(),
        (
            "The Data Processing App formula domain uses the exact PostgreSQL tables "
            f"{formula_tables}. The main joins are formula.id = formula_variable.formula_id, "
            "formula.id = formula_chart.formula_id, formula.id = formula_result_snapshot.formula_id, "
            "bulk_formula.id = bulk_formula_group.bulk_formula_id, "
            "bulk_formula_group.id = bulk_formula_group_mapping.group_id, and "
            "bulk_formula_group.formula_id = formula.id. "
            "formula_chart.data_id matches formula_result_snapshot.chart_data_id for chart outputs."
        ),
        (
            "The validation domain uses the exact tables "
            f"{validation_tables}. The main joins are validation_rule.id = validation_variable.validation_rule_id, "
            "bulk_validation_rule.id = bulk_validation_variable.bulk_validation_rule_id, "
            "bulk_validation_rule.id = bulk_validation_group.bulk_validation_rule_id, "
            "bulk_validation_group.id = bulk_validation_group_mapping.group_id, and "
            "bulk_validation_group.validation_rule_id = validation_rule.id. "
            "The current schema stores definitions and mappings, not trigger-frequency history."
        ),
        (
            "The aggregation domain uses the exact tables "
            f"{aggregation_tables}. The main joins are aggregation_rule.id = aggregation_rule_datapoint.rule_id, "
            "aggregation_rule.id = aggregation_result.rule_id, and aggregation_rule.id = aggregation_run_audit.rule_id. "
            "aggregation_result currently stores id, rule_id, value, time, agg_type, quality, source_count, created_at, and interval. "
            "The current schema no longer has aggregation_result.data_id, aggregation_result.window_start, or aggregation_result.window_end."
        ),
        (
            "Questions about formula, validation, and aggregation architecture should be answerable from Vector DB guidance first. "
            "Questions about specific rows, counts, latest runs, snapshots, mapped datapoints, statuses, or audit messages should add Data Processing DB evidence."
        ),
        (
            "When the assistant generates SQL for the Data Processing DB, it must use a read-only approach: "
            "single-statement SELECT or WITH ... SELECT only, allowlisted tables and columns, no INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, MERGE, or COPY."
        ),
        (
            "Formula relationship guide: formula is the parent table. "
            "formula joins to formula_variable on formula.id = formula_variable.formula_id. "
            "formula joins to formula_chart on formula.id = formula_chart.formula_id. "
            "formula joins to formula_result_snapshot on formula.id = formula_result_snapshot.formula_id. "
            "To connect a bulk formula instance back to a concrete formula row, use bulk_formula_group.formula_id = formula.id."
        ),
        (
            "Bulk formula relationship guide: bulk_formula is the template header. "
            "bulk_formula joins to bulk_formula_variable on bulk_formula.id = bulk_formula_variable.bulk_formula_id. "
            "bulk_formula joins to bulk_formula_group on bulk_formula.id = bulk_formula_group.bulk_formula_id. "
            "bulk_formula_group joins to bulk_formula_group_mapping on bulk_formula_group.id = bulk_formula_group_mapping.group_id. "
            "To find which concrete datapoint fills which bulk variable, read bulk_formula_group_mapping.variable_name and bulk_formula_group_mapping.datapoint_id."
        ),
        (
            "Formula snapshot relationship guide: formula_result_snapshot stores persisted outputs by formula_id and chart_data_id. "
            "formula_chart stores the chart output data_id for the same formula. "
            "When matching a chart row to its stored result snapshot, join formula_chart.data_id = formula_result_snapshot.chart_data_id and also keep formula_id aligned."
        ),
        (
            "Formula few-shot example for counting formulas: "
            "SELECT COUNT(*) AS formula_count FROM formula. "
            "Use this pattern for questions like how many formulas exist in the Data Processing DB."
        ),
        (
            "Formula few-shot example for listing a formula's datapoints: "
            "SELECT f.id, f.name, fv.variable_name, fv.datapoint_id "
            "FROM formula f "
            "LEFT JOIN formula_variable fv ON fv.formula_id = f.id "
            "WHERE lower(f.name) = lower('target_formula_name') "
            "ORDER BY fv.variable_name. "
            "Use this pattern when the user asks which datapoints feed a named formula."
        ),
        (
            "Formula few-shot example for latest persisted snapshot: "
            "SELECT f.id, f.name, frs.chart_data_id, frs.result_value, frs.computed_at "
            "FROM formula f "
            "LEFT JOIN formula_result_snapshot frs ON frs.formula_id = f.id "
            "WHERE lower(f.name) = lower('target_formula_name') "
            "ORDER BY frs.computed_at DESC NULLS LAST "
            "LIMIT 1. "
            "Use this pattern for latest formula result or snapshot questions."
        ),
        (
            "Bulk formula few-shot example for finding a bulk formula's groups and mapped datapoints: "
            "SELECT bf.id, bf.name, bfg.group_key, bfg.group_name, bfg.result_data_id, bfgm.variable_name, bfgm.datapoint_id "
            "FROM bulk_formula bf "
            "LEFT JOIN bulk_formula_group bfg ON bfg.bulk_formula_id = bf.id "
            "LEFT JOIN bulk_formula_group_mapping bfgm ON bfgm.group_id = bfg.id "
            "ORDER BY bf.id, bfg.group_key, bfgm.variable_name. "
            "Use this path to explain which group belongs to which bulk formula and which datapoints populate the group."
        ),
        (
            "If the question asks which bulk formula group produced a concrete formula row, join bulk_formula_group.formula_id = formula.id, "
            "then read bulk_formula_group.bulk_formula_id to reach the bulk_formula template and bulk_formula_group.id to reach bulk_formula_group_mapping."
        ),
        (
            "Validation relationship guide: validation_rule is the parent rule table. "
            "validation_rule joins to validation_variable on validation_rule.id = validation_variable.validation_rule_id. "
            "bulk_validation_group.validation_rule_id points to the concrete validation_rule created or linked for that bulk group."
        ),
        (
            "Bulk validation relationship guide: bulk_validation_rule is the template header. "
            "bulk_validation_rule joins to bulk_validation_variable on bulk_validation_rule.id = bulk_validation_variable.bulk_validation_rule_id. "
            "bulk_validation_rule joins to bulk_validation_group on bulk_validation_rule.id = bulk_validation_group.bulk_validation_rule_id. "
            "bulk_validation_group joins to bulk_validation_group_mapping on bulk_validation_group.id = bulk_validation_group_mapping.group_id."
        ),
        (
            "Validation few-shot example for rule and datapoint mapping: "
            "SELECT vr.id, vr.name, vr.rule_text, vv.variable_name, vv.datapoint_id "
            "FROM validation_rule vr "
            "LEFT JOIN validation_variable vv ON vv.validation_rule_id = vr.id "
            "ORDER BY vr.id, vv.variable_name. "
            "Use this pattern when the user asks which datapoints are validated by which rule."
        ),
        (
            "Bulk validation few-shot example for template groups and mapped datapoints: "
            "SELECT bvr.id, bvr.name, bvg.group_key, bvg.group_name, bvgm.variable_name, bvgm.datapoint_id, bvg.validation_rule_id "
            "FROM bulk_validation_rule bvr "
            "LEFT JOIN bulk_validation_group bvg ON bvg.bulk_validation_rule_id = bvr.id "
            "LEFT JOIN bulk_validation_group_mapping bvgm ON bvgm.group_id = bvg.id "
            "ORDER BY bvr.id, bvg.group_key, bvgm.variable_name. "
            "Use this path when the user asks which bulk validation group belongs to which bulk validation rule."
        ),
        (
            "Validation business-rule note: the current schema stores validation definitions and datapoint mappings, "
            "but it does not store validation trigger frequency, pass-rate history, or per-rule execution counts. "
            "If the user asks which validation rule is used most often, the correct answer is that the current internal schema does not contain that history."
        ),
        (
            "Aggregation relationship guide: aggregation_rule is the parent rule table. "
            "aggregation_rule joins to aggregation_rule_datapoint on aggregation_rule.id = aggregation_rule_datapoint.rule_id. "
            "aggregation_rule joins to aggregation_result on aggregation_rule.id = aggregation_result.rule_id. "
            "aggregation_rule joins to aggregation_run_audit on aggregation_rule.id = aggregation_run_audit.rule_id."
        ),
        (
            "Aggregation schema caveat: aggregation_result is a reshaped table. "
            "The current schema uses columns rule_id, value, time, agg_type, quality, source_count, created_at, and interval. "
            "Do not assume aggregation_result still has data_id, window_start, window_end, rule_name, interval_value, or interval_unit."
        ),
        (
            "Aggregation few-shot example for latest run audit: "
            "SELECT ar.id AS rule_id, ar.name AS rule_name, ara.started_at, ara.completed_at, ara.status, ara.processed_count, ara.inserted_count, ara.message "
            "FROM aggregation_rule ar "
            "JOIN aggregation_run_audit ara ON ara.rule_id = ar.id "
            "ORDER BY ara.started_at DESC NULLS LAST, ara.id DESC "
            "LIMIT 1. "
            "Use this pattern when the user asks for the latest aggregation run."
        ),
        (
            "Aggregation few-shot example for failed runs: "
            "SELECT ar.id AS rule_id, ar.name AS rule_name, ara.window_start, ara.window_end, ara.status, ara.message "
            "FROM aggregation_rule ar "
            "JOIN aggregation_run_audit ara ON ara.rule_id = ar.id "
            "WHERE upper(coalesce(ara.status, '')) = 'FAILED' "
            "ORDER BY ara.started_at DESC NULLS LAST, ara.id DESC "
            "LIMIT 20. "
            "Use this pattern for questions about failed aggregation jobs."
        ),
        (
            "Aggregation few-shot example for rules filtered by interval and method: "
            "SELECT ar.id, ar.name, ar.interval_value, ar.interval_unit, ar.method, ar.gap_filling_mode, ar.enabled "
            "FROM aggregation_rule ar "
            "WHERE ar.interval_value = 15 AND lower(ar.interval_unit) = lower('minute') "
            "ORDER BY ar.id. "
            "Use this pattern when the user asks for 15 minute, 1 hour, average, min, max, or similar aggregation rule filters."
        ),
        (
            "Aggregation few-shot example for recent persisted outputs: "
            "SELECT ar.id, ar.name, agr.value, agr.time, agr.agg_type, agr.quality, agr.source_count, agr.interval "
            "FROM aggregation_rule ar "
            "JOIN aggregation_result agr ON agr.rule_id = ar.id "
            "ORDER BY agr.time DESC NULLS LAST, agr.id DESC "
            "LIMIT 20. "
            "Use this pattern when the user asks for actual aggregated result rows rather than audit rows."
        ),
        (
            "Cross-domain join note: formula and validation domains do not directly share a dedicated bridge table. "
            "Their practical connection is usually through datapoint ids in formula_variable.datapoint_id, validation_variable.datapoint_id, "
            "bulk_formula_group_mapping.datapoint_id, and bulk_validation_group_mapping.datapoint_id. "
            "If a question asks which validations affect a formula, compare shared datapoint ids across those mapping tables."
        ),
        (
            "Cross-domain few-shot example for finding validations relevant to a formula by shared datapoint ids: "
            "SELECT DISTINCT f.id, f.name, vv.validation_rule_id, vr.name AS validation_rule_name, fv.datapoint_id "
            "FROM formula f "
            "JOIN formula_variable fv ON fv.formula_id = f.id "
            "JOIN validation_variable vv ON vv.datapoint_id = fv.datapoint_id "
            "JOIN validation_rule vr ON vr.id = vv.validation_rule_id "
            "WHERE lower(f.name) = lower('target_formula_name') "
            "ORDER BY vr.name, fv.datapoint_id. "
            "Use this pattern when the user asks which validation rules are related to a specific formula."
        ),
        (
            "Read-only SQL generation rule of thumb: choose the narrowest parent table first, join outward through the known foreign-key path, "
            "prefer stable ORDER BY clauses on timestamps or ids, and always cap row counts with LIMIT unless the user explicitly asks for a total count."
        ),
    ]
