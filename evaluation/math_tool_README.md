# Math Tool Evaluation

This evaluation measures how reliably different model sizes use a Python-based math tool.

Scope:

- tool-choice behavior
- tool-argument formulation
- tool execution correctness
- final answer accuracy
- model comparison across `3B`, `7B`, and `7B+`

Run from the repo root:

```powershell
.\myenv\Scripts\python.exe scripts/run_math_tool_eval.py
```

Outputs:

- `reports/math_tool_eval_results.json`
- `reports/math_tool_eval_report.md`
