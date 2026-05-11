from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger("rag.mock_product_schema")

SCHEMA_FILENAME = "mock-npm-llm-schema.json"
SCHEMA_PATH = Path(__file__).resolve().parents[1] / SCHEMA_FILENAME


@lru_cache(maxsize=1)
def load_mock_product_schema() -> dict[str, Any] | None:
    if not SCHEMA_PATH.exists():
        logger.info("mock product schema file not found at %s", SCHEMA_PATH)
        return None

    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("failed to load mock product schema from %s error=%s", SCHEMA_PATH, exc)
        return None


def has_mock_product_schema() -> bool:
    return load_mock_product_schema() is not None


def mock_product_tables() -> list[str]:
    schema = load_mock_product_schema()
    if not schema:
        return []
    return [str(table.get("name") or "").strip() for table in schema.get("tables", []) if table.get("name")]


def _table_lookup() -> dict[str, dict[str, Any]]:
    schema = load_mock_product_schema()
    if not schema:
        return {}
    return {
        str(table.get("name")): table
        for table in schema.get("tables", [])
        if table.get("name")
    }


def _format_column_prompt(column: dict[str, Any]) -> str:
    name = str(column.get("name") or "").strip()
    type_name = str(column.get("type") or "unknown").strip()
    nullable = bool(column.get("nullable", True))
    description = str(column.get("description") or "").strip()

    parts = [f"{name} {type_name}"]
    if not nullable:
        parts.append("NOT NULL")
    if description:
        parts.append(f"- {description}")
    return " ".join(parts).strip()


def _join_hints_for_table(table: dict[str, Any], known_tables: set[str]) -> list[str]:
    joins = list(table.get("joins", []))
    foreign_keys = table.get("foreign_keys", []) or []
    for fk in foreign_keys:
        column = str(fk.get("column") or "").strip()
        reference = str(fk.get("references") or "").strip()
        if not column or "." not in reference:
            continue
        reference_table = reference.split(".", 1)[0]
        if reference_table not in known_tables:
            continue
        joins.append(f"{table['name']}.{column} = {reference}")
    return joins


def build_mock_product_sql_schema_prompt() -> str:
    schema = load_mock_product_schema()
    if not schema:
        return ""

    table_lookup = _table_lookup()
    known_tables = set(table_lookup)
    lines: list[str] = []
    for table_name in mock_product_tables():
        table = table_lookup[table_name]
        columns = [_format_column_prompt(column) for column in table.get("columns", [])]
        joins = _join_hints_for_table(table, known_tables)

        lines.append(f"TABLE {table_name}")
        lines.append(f"DESCRIPTION: {table.get('description', '')}")
        lines.append("COLUMNS: " + ", ".join(columns))

        primary_key = table.get("primary_key") or []
        if primary_key:
            lines.append("PRIMARY KEY: " + ", ".join(str(item) for item in primary_key))

        unique_keys = table.get("unique_keys") or []
        if unique_keys:
            formatted_unique = []
            for unique_key in unique_keys:
                if isinstance(unique_key, list):
                    formatted_unique.append("(" + ", ".join(str(item) for item in unique_key) + ")")
            if formatted_unique:
                lines.append("UNIQUE KEYS: " + " | ".join(formatted_unique))

        if joins:
            lines.append("JOINS: " + " | ".join(joins))
        lines.append("")

    return "\n".join(lines).strip()


def _build_table_catalog_documents(schema: dict[str, Any]) -> list[str]:
    table_lookup = _table_lookup()
    known_tables = set(table_lookup)
    docs: list[str] = []

    for table_name in mock_product_tables():
        table = table_lookup[table_name]
        joins = _join_hints_for_table(table, known_tables)
        join_text = " | ".join(joins) if joins else "No documented joins."
        column_names = ", ".join(str(column.get("name") or "") for column in table.get("columns", []))
        docs.append(
            (
                f"Schema catalog for product table {table_name}: domain=product. "
                f"Business meaning: {table.get('description', '')} "
                f"Columns: {column_names}. "
                f"Known joins: {join_text}"
            )
        )

    return docs


def build_mock_product_rag_documents() -> list[str]:
    schema = load_mock_product_schema()
    if not schema:
        return []

    schema_name = str(schema.get("schema_name") or "mock_product")
    version = str(schema.get("version") or "unknown")
    purpose = str(schema.get("purpose") or "").strip()
    relationship_hints = [str(item).strip() for item in schema.get("relationship_hints", []) if str(item).strip()]
    query_patterns = [str(item).strip() for item in schema.get("query_patterns", []) if str(item).strip()]
    table_names = ", ".join(mock_product_tables())

    docs = [
        (
            f"The product monitoring mock schema {schema_name} version {version} is available as an internal demo schema. "
            f"Purpose: {purpose} "
            f"It is a structured operational water-utility style schema, separate from the formula, validation, aggregation, and npm demo tables."
        ),
        *_build_table_catalog_documents(schema),
        (
            f"The product domain uses the exact PostgreSQL tables {table_names}. "
            "Core operational queries usually join assets, dataDefinition, measurementType, districtInfo, and either s_data_current for latest values or s_data for historical values."
        ),
        (
            "Product schema query guidance: use s_data_current for latest dashboard-style values, one row per register and interval. "
            "Use s_data for time-series history, trends, daily aggregates, and comparisons to historical averages."
        ),
        (
            "Product schema join guidance: assets.id joins to dataDefinition.assetId. "
            "dataDefinition.register joins to s_data.dataid and s_data_current.dataid. "
            "dataDefinition.measurementTypeId joins to measurementType.id. "
            "assets.district joins to districtInfo.id and assets.region joins to region.id."
        ),
        (
            "Product schema business meanings: measurementType defines semantics like flow, pressure, level, consumption, or leakage. "
            "operationArea, region, and districtInfo provide geography and service hierarchy. "
            "waterBalance stores configured loss and billing components per asset and interval."
        ),
        (
            "Product SQL generation rule of thumb: for counts use COUNT(*) with a clear alias such as asset_count or active_register_count. "
            "For latest values, order by the current or historical timestamp descending and keep a LIMIT. "
            "For no-related-record questions, prefer LEFT JOIN plus IS NULL on the related table."
        ),
        (
            "Product few-shot example for counting assets: "
            "SELECT COUNT(*) AS asset_count FROM assets. "
            "Use this pattern for questions asking how many assets, facilities, or monitored entities exist."
        ),
        (
            "Product few-shot example for the latest pressure by district: "
            "SELECT a.label AS asset_label, di.name AS district_name, sdc.value, sdc.ze1 "
            "FROM assets a "
            "JOIN districtInfo di ON di.id = a.district "
            "JOIN dataDefinition dd ON dd.assetId = a.id "
            "JOIN measurementType mt ON mt.id = dd.measurementTypeId "
            "JOIN s_data_current sdc ON sdc.dataid = dd.register "
            "WHERE lower(mt.name) = lower('pressure') "
            "ORDER BY sdc.ze1 DESC NULLS LAST "
            "LIMIT 20."
        ),
        (
            "Product few-shot example for historical flow by region: "
            "SELECT r.name AS region_name, date(sd.ze1) AS day, SUM(sd.value) AS total_flow "
            "FROM region r "
            "JOIN assets a ON a.region = r.id "
            "JOIN dataDefinition dd ON dd.assetId = a.id "
            "JOIN measurementType mt ON mt.id = dd.measurementTypeId "
            "JOIN s_data sd ON sd.dataid = dd.register "
            "WHERE lower(mt.name) = lower('flow') "
            "GROUP BY r.name, date(sd.ze1) "
            "ORDER BY day DESC, region_name."
        ),
        (
            "Product few-shot example for assets without active registers: "
            "SELECT a.id, a.label, a.type "
            "FROM assets a "
            "LEFT JOIN dataDefinition dd ON dd.assetId = a.id AND coalesce(dd.isActive, false) = true "
            "WHERE dd.id IS NULL "
            "ORDER BY a.id."
        ),
    ]

    if relationship_hints:
        docs.append(
            "Product relationship hints: " + " | ".join(relationship_hints)
        )

    if query_patterns:
        docs.append(
            "Representative product questions supported by the schema: " + " | ".join(query_patterns)
        )

    return docs
