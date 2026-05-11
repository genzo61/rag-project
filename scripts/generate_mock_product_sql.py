from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "mock-npm-llm-schema.json"
OUTPUT_DIR = ROOT / "scripts" / "sql"
SCHEMA_SQL_PATH = OUTPUT_DIR / "mock_product_schema.sql"
SEED_SQL_PATH = OUTPUT_DIR / "mock_product_seed.sql"


def load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def pg_type(type_name: str) -> str:
    normalized = (type_name or "").strip().lower()
    mapping = {
        "integer": "INTEGER",
        "bigint": "BIGINT",
        "varchar": "TEXT",
        "text": "TEXT",
        "double": "DOUBLE PRECISION",
        "float": "DOUBLE PRECISION",
        "timestamp": "TIMESTAMP",
        "boolean": "BOOLEAN",
        "jsonb": "JSONB",
    }
    return mapping.get(normalized, "TEXT")


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, dict):
        text = json.dumps(value, ensure_ascii=True).replace("'", "''")
        return f"'{text}'::jsonb"

    text = str(value).replace("'", "''")
    return f"'{text}'"


def build_create_table_sql(schema: dict[str, Any]) -> str:
    statements: list[str] = [
        "-- Auto-generated from mock-npm-llm-schema.json",
        "BEGIN;",
    ]
    table_names = {str(table["name"]) for table in schema.get("tables", []) if table.get("name")}
    fk_statements: list[str] = []
    index_statements: list[str] = []

    for table in schema.get("tables", []):
        table_name = str(table["name"])
        column_lines: list[str] = []
        for column in table.get("columns", []):
            line = f"    {column['name']} {pg_type(str(column.get('type') or 'text'))}"
            if not bool(column.get("nullable", True)):
                line += " NOT NULL"
            column_lines.append(line)

        primary_key = table.get("primary_key") or []
        if primary_key:
            column_lines.append("    PRIMARY KEY (" + ", ".join(primary_key) + ")")

        for unique_key in table.get("unique_keys", []):
            if isinstance(unique_key, list) and unique_key:
                column_lines.append("    UNIQUE (" + ", ".join(str(item) for item in unique_key) + ")")

        statements.append(f"CREATE TABLE IF NOT EXISTS {table_name} (")
        statements.append(",\n".join(column_lines))
        statements.append(");")
        statements.append("")

        for fk in table.get("foreign_keys", []) or []:
            column = str(fk.get("column") or "")
            reference = str(fk.get("references") or "")
            if not column or "." not in reference:
                continue

            reference_table, reference_column = reference.split(".", 1)
            if reference_table not in table_names:
                statements.append(
                    f"-- Skipped unresolved foreign key {table_name}.{column} -> {reference}"
                )
                continue

            constraint_name = f"fk_{table_name.lower()}_{column.lower()}"
            fk_statements.append(
                f"ALTER TABLE {table_name} "
                f"ADD CONSTRAINT {constraint_name} "
                f"FOREIGN KEY ({column}) REFERENCES {reference_table} ({reference_column});"
            )
            index_statements.append(
                f"CREATE INDEX IF NOT EXISTS idx_{table_name.lower()}_{column.lower()} "
                f"ON {table_name} ({column});"
            )

    statements.extend(fk_statements)
    statements.append("")
    statements.extend(sorted(set(index_statements)))
    statements.append("")
    statements.append("COMMIT;")
    return "\n".join(statements).strip() + "\n"


def _format_ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _build_hourly_history(
    *,
    start_id: int,
    register: str,
    start_at: datetime,
    hours: int,
    base_value: float,
    daily_amplitude: float,
    weekly_amplitude: float,
    interval: str = "1h",
    art: str = "avg",
    type_name: str = "telemetry",
    quality: str = "good",
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    current_id = start_id

    for hour_index in range(hours):
        ze1 = start_at + timedelta(hours=hour_index)
        ze2 = ze1 + timedelta(hours=1)
        hour_of_day = ze1.hour
        weekday = ze1.weekday()

        daily_wave = math.sin((hour_of_day / 24.0) * math.pi * 2.0)
        weekly_wave = math.cos((weekday / 7.0) * math.pi * 2.0)
        trend = (hour_index / max(hours, 1)) * 0.8
        value = base_value + (daily_wave * daily_amplitude) + (weekly_wave * weekly_amplitude) + trend

        rows.append(
            {
                "id": current_id,
                "ze1": _format_ts(ze1),
                "ze2": _format_ts(ze2),
                "dataid": register,
                "value": round(value, 2),
                "interval": interval,
                "art": art,
                "type": type_name,
                "quality": quality,
                "created_at": _format_ts(ze2 + timedelta(minutes=1)),
            }
        )
        current_id += 1

    return rows, current_id


def _build_daily_history(
    *,
    start_id: int,
    register: str,
    start_at: datetime,
    days: int,
    base_value: float,
    step_per_day: float,
    wave_amplitude: float,
    interval: str = "1d",
    art: str = "sum",
    type_name: str = "derived",
    quality: str = "estimated",
) -> tuple[list[dict[str, Any]], int]:
    rows: list[dict[str, Any]] = []
    current_id = start_id

    for day_index in range(days):
        ze1 = start_at + timedelta(days=day_index)
        ze2 = ze1 + timedelta(days=1)
        wave = math.sin((day_index / 7.0) * math.pi * 2.0)
        value = base_value + (day_index * step_per_day) + (wave * wave_amplitude)

        rows.append(
            {
                "id": current_id,
                "ze1": _format_ts(ze1),
                "ze2": _format_ts(ze2),
                "dataid": register,
                "value": round(value, 2),
                "interval": interval,
                "art": art,
                "type": type_name,
                "quality": quality,
                "created_at": _format_ts(ze2 + timedelta(minutes=5)),
            }
        )
        current_id += 1

    return rows, current_id


def _build_s_data_history_rows() -> list[dict[str, Any]]:
    history_start = datetime(2026, 4, 11, 0, 0, 0)
    hours = 24 * 30
    days = 30
    next_id = 9101
    rows: list[dict[str, Any]] = []

    hourly_specs = [
        ("REG_FLOW_DMA_RIVERSIDE", 176.5, 7.5, 2.1),
        ("REG_PRESS_DMA_RIVERSIDE", 4.65, 0.18, 0.05),
        ("REG_LEVEL_RES_NORTH", 7.45, 0.22, 0.08),
        ("REG_FLOW_DMA_HILLTOP", 140.2, 6.0, 1.7),
        ("REG_PRESS_DMA_HILLTOP", 4.15, 0.16, 0.04),
    ]
    for register, base_value, daily_amplitude, weekly_amplitude in hourly_specs:
        history_rows, next_id = _build_hourly_history(
            start_id=next_id,
            register=register,
            start_at=history_start,
            hours=hours,
            base_value=base_value,
            daily_amplitude=daily_amplitude,
            weekly_amplitude=weekly_amplitude,
        )
        rows.extend(history_rows)

    daily_specs = [
        ("REG_CONS_DMA_RIVERSIDE", 3410.0, 3.5, 65.0),
        ("REG_LEAK_DMA_RIVERSIDE", 598.0, 0.9, 18.0),
    ]
    for register, base_value, step_per_day, wave_amplitude in daily_specs:
        history_rows, next_id = _build_daily_history(
            start_id=next_id,
            register=register,
            start_at=history_start,
            days=days,
            base_value=base_value,
            step_per_day=step_per_day,
            wave_amplitude=wave_amplitude,
        )
        rows.extend(history_rows)

    return rows


def build_seed_rows() -> dict[str, list[dict[str, Any]]]:
    return {
        "measurementType": [
            {"id": 1, "name": "flow", "deletable": True, "showInMnfChart": True, "groupId": 10, "hasReverseColors": False},
            {"id": 2, "name": "pressure", "deletable": True, "showInMnfChart": False, "groupId": 10, "hasReverseColors": True},
            {"id": 3, "name": "level", "deletable": True, "showInMnfChart": False, "groupId": 20, "hasReverseColors": False},
            {"id": 4, "name": "consumption", "deletable": True, "showInMnfChart": False, "groupId": 30, "hasReverseColors": False},
            {"id": 5, "name": "leakage", "deletable": True, "showInMnfChart": False, "groupId": 30, "hasReverseColors": True},
        ],
        "measurementPointType": [
            {"id": 1, "name": "reservoir_sensor"},
            {"id": 2, "name": "dma_meter"},
            {"id": 3, "name": "pump_sensor"},
            {"id": 4, "name": "consumer_meter"},
            {"id": 5, "name": "valve_sensor"},
        ],
        "facilityType": [
            {"id": 1, "name": "reservoir"},
            {"id": 2, "name": "pump_station"},
            {"id": 3, "name": "metering_station"},
            {"id": 4, "name": "dma"},
            {"id": 5, "name": "chamber"},
        ],
        "operationArea": [
            {
                "opAreaId": 201,
                "name": "North Operations",
                "area": 82.5,
                "population": 125000,
                "lengthOfMainNetwork": 410.2,
                "numberOfConsumers": 38200,
                "validFrom": "2025-01-01 00:00:00",
                "gisId": "OA-NORTH-201",
                "color": "#1f6f8b",
            },
            {
                "opAreaId": 202,
                "name": "West Operations",
                "area": 61.3,
                "population": 88000,
                "lengthOfMainNetwork": 295.4,
                "numberOfConsumers": 25400,
                "validFrom": "2025-01-01 00:00:00",
                "gisId": "OA-WEST-202",
                "color": "#355070",
            },
        ],
        "region": [
            {"id": 1, "name": "North Region", "city": "DemoCity", "area": 112.4, "population": 145000, "validFrom": "2025-01-01 00:00:00", "gisId": "REG-NORTH-1", "color": "#264653"},
            {"id": 2, "name": "West Region", "city": "DemoCity", "area": 94.9, "population": 101000, "validFrom": "2025-01-01 00:00:00", "gisId": "REG-WEST-2", "color": "#2a9d8f"},
        ],
        "district": [
            {"id": 11, "name": "Riverside"},
            {"id": 12, "name": "Hilltop"},
        ],
        "districtInfo": [
            {"id": 101, "name": "Riverside DMA", "region": 1, "area": 25.6, "population": 42000, "lengthOfMainNetwork": 130.4, "numberOfConsumers": 12100, "validFrom": "2025-01-01 00:00:00", "gisId": "DMA-RIVER-101", "color": "#e76f51"},
            {"id": 102, "name": "Hilltop DMA", "region": 2, "area": 18.2, "population": 28600, "lengthOfMainNetwork": 96.8, "numberOfConsumers": 8400, "validFrom": "2025-01-01 00:00:00", "gisId": "DMA-HILL-102", "color": "#f4a261"},
        ],
        "data_sources": [
            {"id": 1, "name": "SCADA OPC-UA", "type": "opcua", "config": {"endpoint": "opc.tcp://demo-water.local:4840", "site": "north"}, "enabled": True, "created_at": "2026-01-10 08:00:00", "updated_at": "2026-05-10 09:15:00"},
            {"id": 2, "name": "Pressure MQTT Feed", "type": "mqtt", "config": {"broker": "mqtt://demo-water.local:1883", "topic": "pressure/+"}, "enabled": True, "created_at": "2026-01-10 08:10:00", "updated_at": "2026-05-10 09:15:00"},
            {"id": 3, "name": "Formula Engine", "type": "formula", "config": {"engine": "demo-rules", "refresh_minutes": 15}, "enabled": True, "created_at": "2026-01-10 08:20:00", "updated_at": "2026-05-10 09:15:00"},
        ],
        "assets": [
            {"id": 1101, "parentId": None, "type": "reservoir", "label": "North Reservoir A", "gisId": "AST-1101", "longitude": 29.1024, "latitude": 41.0187, "measurementPointTypeId": 1, "facilityTypeId": 1, "opAreaId": 201, "region": 1, "district": 101, "dashboardId": None, "i1": None, "i2": None, "f1": 18.7, "s1": "critical_storage", "color": "#457b9d", "validFrom": "2025-01-01 00:00:00"},
            {"id": 1201, "parentId": 1101, "type": "DMA", "label": "Riverside DMA Inlet", "gisId": "AST-1201", "longitude": 29.1091, "latitude": 41.0205, "measurementPointTypeId": 2, "facilityTypeId": 4, "opAreaId": 201, "region": 1, "district": 101, "dashboardId": None, "i1": 1, "i2": None, "f1": 0.94, "s1": "north_dma", "color": "#e63946", "validFrom": "2025-01-01 00:00:00"},
            {"id": 1301, "parentId": 1101, "type": "pump", "label": "East Pump Station", "gisId": "AST-1301", "longitude": 29.1132, "latitude": 41.0248, "measurementPointTypeId": 3, "facilityTypeId": 2, "opAreaId": 201, "region": 1, "district": 101, "dashboardId": None, "i1": 2, "i2": None, "f1": 3.0, "s1": "booster", "color": "#1d3557", "validFrom": "2025-01-01 00:00:00"},
            {"id": 1401, "parentId": 1201, "type": "valve", "label": "Valve Chamber 7", "gisId": "AST-1401", "longitude": 29.1114, "latitude": 41.0199, "measurementPointTypeId": 5, "facilityTypeId": 5, "opAreaId": 201, "region": 1, "district": 101, "dashboardId": None, "i1": None, "i2": None, "f1": None, "s1": "manual_asset", "color": "#6d597a", "validFrom": "2025-01-01 00:00:00"},
            {"id": 1501, "parentId": None, "type": "DMA", "label": "Hilltop DMA Inlet", "gisId": "AST-1501", "longitude": 29.0715, "latitude": 40.9984, "measurementPointTypeId": 2, "facilityTypeId": 4, "opAreaId": 202, "region": 2, "district": 102, "dashboardId": None, "i1": 1, "i2": None, "f1": 0.91, "s1": "west_dma", "color": "#f77f00", "validFrom": "2025-01-01 00:00:00"},
            {"id": 1601, "parentId": 1201, "type": "meter", "label": "Consumer Meter Block A", "gisId": "AST-1601", "longitude": 29.1107, "latitude": 41.0218, "measurementPointTypeId": 4, "facilityTypeId": 3, "opAreaId": 201, "region": 1, "district": 101, "dashboardId": None, "i1": None, "i2": None, "f1": None, "s1": "consumer_meter", "color": "#8d99ae", "validFrom": "2025-01-01 00:00:00"},
        ],
        "assetProperties": [
            {"id": 1, "assetId": 1101, "i1": 2, "i2": None, "f1": 12500.0, "f2": 8400.0, "d1": "2025-03-15 00:00:00", "d2": "2026-04-20 00:00:00"},
            {"id": 2, "assetId": 1201, "i1": 15, "i2": None, "f1": 1.2, "f2": 0.8, "d1": "2025-02-01 00:00:00", "d2": "2026-05-01 00:00:00"},
            {"id": 3, "assetId": 1501, "i1": 15, "i2": None, "f1": 1.0, "f2": 0.7, "d1": "2025-02-01 00:00:00", "d2": "2026-05-01 00:00:00"},
        ],
        "consumer_profile": [
            {"profileId": 701, "name": "Residential Midrise", "type": "residential", "template_id": None, "asset_id": 1601},
        ],
        "dataDefinition": [
            {"id": 2001, "register": "REG_FLOW_DMA_RIVERSIDE", "label": "Riverside Inlet Flow", "archivePeriod": "15m", "isActive": True, "measurementTypeId": 1, "assetId": 1201, "description": "Primary DMA inflow meter", "unit": "m3/h", "type": "telemetry", "formula": None, "showCurrentValues": True, "opAreaId": 201, "regionId": 1, "districtId": 101, "isPrimary": True, "isDefault": True, "showInMap": True, "availability": 0.995, "automaticCreated": False, "dataSourceId": 1},
            {"id": 2002, "register": "REG_PRESS_DMA_RIVERSIDE", "label": "Riverside Pressure", "archivePeriod": "15m", "isActive": True, "measurementTypeId": 2, "assetId": 1201, "description": "District pressure sensor", "unit": "bar", "type": "telemetry", "formula": None, "showCurrentValues": True, "opAreaId": 201, "regionId": 1, "districtId": 101, "isPrimary": True, "isDefault": True, "showInMap": True, "availability": 0.989, "automaticCreated": False, "dataSourceId": 2},
            {"id": 2003, "register": "REG_LEVEL_RES_NORTH", "label": "North Reservoir Level", "archivePeriod": "15m", "isActive": True, "measurementTypeId": 3, "assetId": 1101, "description": "Reservoir level sensor", "unit": "m", "type": "telemetry", "formula": None, "showCurrentValues": True, "opAreaId": 201, "regionId": 1, "districtId": 101, "isPrimary": True, "isDefault": True, "showInMap": True, "availability": 0.998, "automaticCreated": False, "dataSourceId": 1},
            {"id": 2004, "register": "REG_CONS_DMA_RIVERSIDE", "label": "Riverside Billed Consumption", "archivePeriod": "1d", "isActive": True, "measurementTypeId": 4, "assetId": 1601, "description": "Aggregated billed demand", "unit": "m3/d", "type": "derived", "formula": "SUM(zone_consumption)", "showCurrentValues": True, "opAreaId": 201, "regionId": 1, "districtId": 101, "isPrimary": False, "isDefault": True, "showInMap": False, "availability": 0.971, "automaticCreated": True, "dataSourceId": 3},
            {"id": 2005, "register": "REG_LEAK_DMA_RIVERSIDE", "label": "Riverside Estimated Leakage", "archivePeriod": "1d", "isActive": True, "measurementTypeId": 5, "assetId": 1201, "description": "Estimated leakage KPI", "unit": "m3/d", "type": "derived", "formula": "input-consumption-authorized", "showCurrentValues": True, "opAreaId": 201, "regionId": 1, "districtId": 101, "isPrimary": False, "isDefault": False, "showInMap": True, "availability": 0.96, "automaticCreated": True, "dataSourceId": 3},
            {"id": 2006, "register": "REG_FLOW_DMA_HILLTOP", "label": "Hilltop Inlet Flow", "archivePeriod": "15m", "isActive": True, "measurementTypeId": 1, "assetId": 1501, "description": "Primary DMA inflow meter", "unit": "m3/h", "type": "telemetry", "formula": None, "showCurrentValues": True, "opAreaId": 202, "regionId": 2, "districtId": 102, "isPrimary": True, "isDefault": True, "showInMap": True, "availability": 0.991, "automaticCreated": False, "dataSourceId": 1},
            {"id": 2007, "register": "REG_PRESS_DMA_HILLTOP", "label": "Hilltop Pressure", "archivePeriod": "15m", "isActive": True, "measurementTypeId": 2, "assetId": 1501, "description": "District pressure sensor", "unit": "bar", "type": "telemetry", "formula": None, "showCurrentValues": True, "opAreaId": 202, "regionId": 2, "districtId": 102, "isPrimary": True, "isDefault": True, "showInMap": True, "availability": 0.984, "automaticCreated": False, "dataSourceId": 2},
            {"id": 2008, "register": "REG_FLOW_PUMP_EAST", "label": "East Pump Station Flow", "archivePeriod": "15m", "isActive": False, "measurementTypeId": 1, "assetId": 1301, "description": "Disabled meter for maintenance demo", "unit": "m3/h", "type": "telemetry", "formula": None, "showCurrentValues": False, "opAreaId": 201, "regionId": 1, "districtId": 101, "isPrimary": False, "isDefault": False, "showInMap": False, "availability": 0.54, "automaticCreated": False, "dataSourceId": 1},
        ],
        "waterBalance": [
            {"id": 3001, "assetId": 1201, "interval": "1d", "systemInputId": 2001, "billMeteredId": 2004, "billUnmeteredId": None, "unbillMetered": 8.5, "unbillUnmetered": 3.1, "unauthConsumption": 1.4, "customerInacuracy": 2.7, "leakageNetwork": 14.8, "leakageReservoir": 0.9, "leakageService": 4.2, "isDefault": True, "recordDate": "2026-05-10 00:00:00", "createdAt": "2026-05-10 05:00:00", "updatedAt": "2026-05-10 05:00:00"},
            {"id": 3002, "assetId": 1501, "interval": "1d", "systemInputId": 2006, "billMeteredId": None, "billUnmeteredId": None, "unbillMetered": 5.2, "unbillUnmetered": 2.0, "unauthConsumption": 0.8, "customerInacuracy": 1.8, "leakageNetwork": 9.7, "leakageReservoir": 0.5, "leakageService": 2.9, "isDefault": True, "recordDate": "2026-05-10 00:00:00", "createdAt": "2026-05-10 05:10:00", "updatedAt": "2026-05-10 05:10:00"},
        ],
        "s_data_current": [
            {"dataid": "REG_FLOW_DMA_RIVERSIDE", "interval": "15m", "type": "telemetry", "ze1": "2026-05-11 08:00:00", "ze2": "2026-05-11 08:15:00", "value": 182.4, "id": 9001, "art": "avg", "quality": "good"},
            {"dataid": "REG_PRESS_DMA_RIVERSIDE", "interval": "15m", "type": "telemetry", "ze1": "2026-05-11 08:00:00", "ze2": "2026-05-11 08:15:00", "value": 4.8, "id": 9002, "art": "avg", "quality": "good"},
            {"dataid": "REG_LEVEL_RES_NORTH", "interval": "15m", "type": "telemetry", "ze1": "2026-05-11 08:00:00", "ze2": "2026-05-11 08:15:00", "value": 7.2, "id": 9003, "art": "avg", "quality": "good"},
            {"dataid": "REG_CONS_DMA_RIVERSIDE", "interval": "1d", "type": "derived", "ze1": "2026-05-10 00:00:00", "ze2": "2026-05-11 00:00:00", "value": 3520.0, "id": 9004, "art": "sum", "quality": "estimated"},
            {"dataid": "REG_LEAK_DMA_RIVERSIDE", "interval": "1d", "type": "derived", "ze1": "2026-05-10 00:00:00", "ze2": "2026-05-11 00:00:00", "value": 621.0, "id": 9005, "art": "sum", "quality": "estimated"},
            {"dataid": "REG_FLOW_DMA_HILLTOP", "interval": "15m", "type": "telemetry", "ze1": "2026-05-11 08:00:00", "ze2": "2026-05-11 08:15:00", "value": 143.1, "id": 9006, "art": "avg", "quality": "good"},
            {"dataid": "REG_PRESS_DMA_HILLTOP", "interval": "15m", "type": "telemetry", "ze1": "2026-05-11 08:00:00", "ze2": "2026-05-11 08:15:00", "value": 4.3, "id": 9007, "art": "avg", "quality": "good"},
        ],
        "s_data": _build_s_data_history_rows(),
    }


def build_seed_sql(schema: dict[str, Any]) -> str:
    rows_by_table = build_seed_rows()
    ordered_tables = [
        "measurementType",
        "measurementPointType",
        "facilityType",
        "operationArea",
        "region",
        "district",
        "districtInfo",
        "data_sources",
        "assets",
        "assetProperties",
        "consumer_profile",
        "dataDefinition",
        "waterBalance",
        "s_data_current",
        "s_data",
    ]
    truncate_tables = ", ".join(reversed(ordered_tables))

    statements: list[str] = [
        "-- Auto-generated seed data for the mock product schema",
        "BEGIN;",
        f"TRUNCATE TABLE {truncate_tables} RESTART IDENTITY CASCADE;",
        "",
    ]

    for table_name in ordered_tables:
        rows = rows_by_table.get(table_name, [])
        if not rows:
            continue

        columns = list(rows[0].keys())
        statements.append(f"INSERT INTO {table_name} (" + ", ".join(columns) + ") VALUES")
        value_lines: list[str] = []
        for row in rows:
            value_lines.append(
                "    ("
                + ", ".join(sql_literal(row.get(column)) for column in columns)
                + ")"
            )
        statements.append(",\n".join(value_lines) + ";")
        statements.append("")

    statements.extend(
        [
            "UPDATE assets",
            "SET i2 = 701",
            "WHERE id = 1601;",
            "",
            "COMMIT;",
        ]
    )

    return "\n".join(statements).strip() + "\n"


def main() -> None:
    schema = load_schema()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    SCHEMA_SQL_PATH.write_text(build_create_table_sql(schema), encoding="utf-8")
    SEED_SQL_PATH.write_text(build_seed_sql(schema), encoding="utf-8")
    print(f"Wrote {SCHEMA_SQL_PATH}")
    print(f"Wrote {SEED_SQL_PATH}")


if __name__ == "__main__":
    main()
