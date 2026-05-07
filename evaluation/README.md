# Hallucination Evaluation

This folder contains the assets for measuring grounding quality across four answer modes:

- `vector_db`
- `dp_db`
- `web_search`
- `combined_sources`

Files:

- `test_questions.json`: 20-question evaluation set
- `dp_facts.json`: small structured fact store used as the DP DB
- `web_sources.json`: public web sources fetched for the web-search mode

Run the evaluation from the repo root:

```powershell
py -3 scripts/run_hallucination_eval.py
```

Outputs:

- `reports/hallucination_eval_results.json`
- `reports/hallucination_eval_report.md`
- `reports/hallucination_eval_vector_db.md`
- `reports/hallucination_eval_dp_db.md`
- `reports/hallucination_eval_web_search.md`
- `reports/hallucination_eval_combined_sources.md`

## Math Tool Evaluation

This repo also includes a separate math-tool evaluation flow for comparing model sizes on Python-backed tool use.

Files:

- `math_tool_test_cases.json`: arithmetic, multi-step, structured numeric, and conceptual control cases
- `math_tool_README.md`: math-tool evaluation notes

Run from the repo root:

```powershell
.\myenv\Scripts\python.exe scripts/run_math_tool_eval.py
```

Outputs:

- `reports/math_tool_eval_results.json`
- `reports/math_tool_eval_report.md`
