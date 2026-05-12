# DP RAG SQL Evaluation

Generated at: 2026-05-11T07:38:16.608381+00:00

## RAG Population Audit
- PASS `table_descriptions`
- PASS `column_meanings`
- PASS `relationships`
- PASS `units_and_business_meanings`
- PASS `example_sql_patterns`
- PASS `kpi_definitions`
- PASS `known_query_limitations`

## Summary
- Pass: 0
- Partial: 6
- Fail: 3
- Required improvements:
  - Add or refine RAG chunks so the retrieved context consistently names the required tables, columns, and business semantics.
  - Tighten SQL generation prompts or few-shot patterns so the generated SQL uses the expected join path and predicates.
  - Strengthen SQL validation and not-answerable handling when the schema lacks the requested KPI or history.

## Cases
### dp_rag_00 [PARTIAL]
Sistemimde kac tane aggregiation rule var?

- Domains: aggregation
- Tables: aggregation_result
- Failed checks: required_tables_ok, required_sql_fragments_ok

SQL:
```sql
SELECT COUNT(*) AS count FROM aggregation_result
LIMIT 5
```

### dp_rag_01 [PARTIAL]
How many formulas exist in the Data Processing DB?

- Domains: formula
- Tables: formula
- Failed checks: required_context_terms_ok

SQL:
```sql
SELECT COUNT(*) AS formula_count FROM formula LIMIT 5
```

### dp_rag_02 [PARTIAL]
Which datapoints feed the formula named 'PressureLoss'?

- Domains: formula
- Tables: formula, formula_variable
- Failed checks: required_sql_fragments_ok

SQL:
```sql
SELECT 
    f.id AS sql,
    fv.variable_name AS rationale
FROM 
    formula f
LEFT JOIN 
    formula_variable fv ON fv.formula_id = f.id
WHERE 
    lower(f.name) = lower('PressureLoss')
ORDER BY 
    fv.variable_name
LIMIT 10
```

### dp_rag_03 [PARTIAL]
What is the latest persisted snapshot for the formula named 'PressureLoss'?

- Domains: formula
- Tables: formula, formula_result_snapshot
- Failed checks: required_sql_fragments_ok

SQL:
```sql
SELECT 
    f.id,
    f.name,
    frs.chart_data_id,
    frs.result_value,
    MAX(frs.computed_at) AS computed_at
FROM 
    formula f
LEFT JOIN 
    formula_result_snapshot frs ON frs.formula_id = f.id
WHERE 
    lower(f.name) = lower('PressureLoss')
GROUP BY 
    f.id, f.name, frs.chart_data_id, frs.result_value
ORDER BY 
    computed_at DESC NULLS LAST LIMIT 5
```

### dp_rag_04 [FAIL]
What is the latest aggregation run?

- Domains: aggregation
- Tables: aggregation_result
- Failed checks: required_context_terms_ok, required_tables_ok, required_sql_fragments_ok, forbidden_tables_ok

SQL:
```sql
SELECT 
    ar.id,
    ar.value,
    ar.time,
    ar.agg_type,
    ar.quality,
    ar.source_count,
    ar.created_at,
    ar.interval
FROM 
    aggregation_result ar
WHERE 
    ar.time = (SELECT MAX(time) FROM aggregation_result)
LIMIT 5
```

### dp_rag_05 [FAIL]
Which aggregation runs failed recently?

- Domains: aggregation
- Tables: aggregation_result
- Failed checks: required_context_terms_ok, required_tables_ok, required_sql_fragments_ok, forbidden_tables_ok

SQL:
```sql
SELECT 
    time,
    agg_type,
    COUNT(*) AS failed_count
FROM 
    aggregation_result
WHERE 
    (time > NOW() - INTERVAL '1 hour') AND (quality < 0)
GROUP BY 
    time, agg_type
ORDER BY 
    time DESC
LIMIT 10
```

### dp_rag_06 [PARTIAL]
List 15 minute aggregation rules that use the average method.

- Domains: aggregation
- Tables: aggregation_rule
- Failed checks: required_sql_fragments_ok

SQL:
```sql
SELECT ar.id, ar.name, ar.interval_value, ar.interval_unit, ar.method, ar.gap_filling_mode, ar.enabled 
FROM aggregation_rule ar 
WHERE ar.interval_value = 15 AND lower(ar.interval_unit) = lower('minute') 
ORDER BY ar.id LIMIT 10
```

### dp_rag_07 [PARTIAL]
Which validation rules are related to the formula named 'PressureLoss' through shared datapoints?

- Domains: formula, validation
- Tables: formula, formula_variable, validation_variable, validation_rule
- Failed checks: sql_valid
- Validation error: Referenced SQL alias was not declared in FROM/JOIN: v

SQL:
```sql
SELECT DISTINCT 
    v.validation_rule_id,
    vr.name AS validation_rule_name
FROM 
    formula f JOIN formula_variable fv ON fv.formula_id = f.id
JOIN 
    validation_variable vv ON vv.datapoint_id = fv.datapoint_id
JOIN 
    validation_rule vr ON vr.id = vv.validation_rule_id
WHERE 
    lower(f.name) = lower('PressureLoss')
ORDER BY 
    vr.name, fv.datapoint_id
LIMIT 10;
```

### dp_rag_08 [FAIL]
Which validation rule is used most often?

- Domains: validation
- Tables: validation_rule
- Failed checks: required_context_terms_ok, sql_valid, required_sql_fragments_ok, not_answerable_ok

SQL:
```sql
SELECT 
    COUNT(*) AS "count"
FROM 
    validation_rule
LIMIT 5
```
