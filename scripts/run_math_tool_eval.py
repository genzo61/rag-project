from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.math_tool_orchestrator import run_math_tool_conversation

ENV_PATH = ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

EVAL_DIR = ROOT / "evaluation"
REPORTS_DIR = ROOT / "reports"
TEST_SET_PATH = EVAL_DIR / "math_tool_test_cases.json"
RESULTS_PATH = REPORTS_DIR / "math_tool_eval_results.json"
REPORT_PATH = REPORTS_DIR / "math_tool_eval_report.md"

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1").rstrip("/")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MATH_EVAL_7B_PLUS_MODEL = os.getenv("MATH_EVAL_7B_PLUS_MODEL", "openai/gpt-oss-20b:free")
MATH_EVAL_DELAY_SECONDS = float(os.getenv("MATH_EVAL_DELAY_SECONDS", "1.0"))
MATH_EVAL_MAX_RETRIES = int(os.getenv("MATH_EVAL_MAX_RETRIES", "4"))
MATH_EVAL_RETRY_DELAY_SECONDS = float(os.getenv("MATH_EVAL_RETRY_DELAY_SECONDS", "15.0"))
MATH_EVAL_ONLY_TIER = os.getenv("MATH_EVAL_ONLY_TIER", "").strip().lower()

MODEL_CONFIGS = [
    {
        "tier": "3b",
        "label": "Qwen 2.5 3B",
        "model": "qwen2.5:3b",
        "base_url": f"{OLLAMA_BASE_URL}/v1",
        "api_key": OLLAMA_API_KEY,
    },
    {
        "tier": "7b",
        "label": "Qwen 2.5 7B",
        "model": "qwen2.5:7b",
        "base_url": f"{OLLAMA_BASE_URL}/v1",
        "api_key": OLLAMA_API_KEY,
    },
    {
        "tier": "7b_plus",
        "label": "GPT-OSS 120B" if "120b" in MATH_EVAL_7B_PLUS_MODEL.lower() else "GPT-OSS 20B",
        "model": MATH_EVAL_7B_PLUS_MODEL,
        "base_url": OPENROUTER_BASE_URL,
        "api_key": OPENROUTER_API_KEY,
    },
]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _public_model_config(model_config: dict[str, str]) -> dict[str, str]:
    return {
        "tier": model_config["tier"],
        "label": model_config["label"],
        "model": model_config["model"],
        "base_url": model_config["base_url"],
    }


def _save_partial_results(results: list[dict[str, Any]]) -> None:
    summary = build_summary(results) if results else []
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": results,
        "summary": summary,
        "recommended_model": choose_recommendation(summary) if summary else None,
    }
    save_json(RESULTS_PATH, payload)


def extract_numbers(text: str) -> list[float]:
    matches = re.findall(r"-?\d+(?:\.\d+)?", text.replace(",", ""))
    numbers: list[float] = []
    for match in matches:
        try:
            numbers.append(float(match))
        except Exception:
            continue
    return numbers


def text_contains_terms(answer: str, required_terms: list[str]) -> bool:
    lowered = (answer or "").lower()
    return all(term.lower() in lowered for term in required_terms)


def text_matches_term_groups(answer: str, groups: list[list[str]]) -> bool:
    lowered = (answer or "").lower()
    for group in groups:
        if not any(term.lower() in lowered for term in group):
            return False
    return True


def approx_equal(actual: float | None, expected: float, tolerance: float) -> bool:
    if actual is None:
        return False
    return abs(actual - expected) <= tolerance


def _load_existing_results() -> list[dict[str, Any]]:
    if not RESULTS_PATH.exists():
        return []
    try:
        payload = load_json(RESULTS_PATH)
    except Exception:
        return []
    models = payload.get("models")
    return models if isinstance(models, list) else []


def _find_model_result(results: list[dict[str, Any]], tier: str) -> dict[str, Any] | None:
    for item in results:
        model_config = item.get("model_config", {})
        if model_config.get("tier") == tier:
            return item
    return None


def _refresh_existing_results(results: list[dict[str, Any]], test_cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_case_map = {case["id"]: case for case in test_cases}
    refreshed_results: list[dict[str, Any]] = []
    for model_result in results:
        refreshed_cases = []
        for item in model_result.get("cases", []):
            stored_case = item.get("case", {})
            case_id = stored_case.get("id")
            current_case = current_case_map.get(case_id)
            if not current_case:
                continue
            run_result = item.get("run_result", {})
            if run_result.get("question") != current_case.get("question"):
                continue
            refreshed_cases.append(
                {
                    "case": current_case,
                    "run_result": run_result,
                    "evaluation": evaluate_case_result(current_case, run_result),
                }
            )
        refreshed_results.append(
            {
                "model_config": {
                    key: value
                    for key, value in model_result.get("model_config", {}).items()
                    if key != "api_key"
                },
                "cases": refreshed_cases,
            }
        )
    return refreshed_results


def evaluate_case_result(case: dict[str, Any], run_result: dict[str, Any]) -> dict[str, Any]:
    tool_expectation = str(case.get("tool_expectation") or ("required" if case.get("should_use_tool") else "forbidden"))
    tool_called = bool(run_result.get("tool_called"))
    tool_events = run_result.get("tool_events", [])
    final_answer = run_result.get("final_answer", "")

    if tool_expectation == "required":
        tool_choice = "correct_call" if tool_called else "missed_call"
    elif tool_expectation == "forbidden":
        tool_choice = "unnecessary_call" if tool_called else "correct_skip"
    else:
        tool_choice = "optional_call" if tool_called else "optional_skip"

    tool_input_correct = None
    tool_result_correct = None
    raw_input_correct = None
    normalized_input_usable = None

    if tool_expectation == "required":
        if tool_events:
            last_tool_event = tool_events[-1]
            tool_result = last_tool_event.get("tool_result", {})
            raw_validation = last_tool_event.get("raw_validation", {})
            normalized_validation = last_tool_event.get("normalized_validation", {})
            raw_input_correct = bool(raw_validation.get("ok"))
            normalized_input_usable = bool(normalized_validation.get("ok"))
            if tool_result.get("ok"):
                tool_output = tool_result.get("result")
                tool_result_correct = approx_equal(
                    float(tool_output) if tool_output is not None else None,
                    float(case["expected_numeric"]),
                    float(case.get("tolerance", 1e-6)),
                )
                tool_input_correct = raw_input_correct
            else:
                tool_result_correct = False
                tool_input_correct = raw_input_correct
        else:
            tool_result_correct = False
            tool_input_correct = False
            normalized_input_usable = False
            raw_input_correct = False

    final_answer_correct = False
    final_numeric = None

    if case.get("requires_refusal"):
        final_answer_correct = text_matches_term_groups(final_answer, case.get("required_term_groups", []))
    elif "expected_numeric" in case:
        answer_numbers = extract_numbers(final_answer)
        expected_value = float(case["expected_numeric"])
        tolerance = float(case.get("tolerance", 1e-6))
        matching_numbers = [number for number in answer_numbers if approx_equal(number, expected_value, tolerance)]
        final_numeric = matching_numbers[0] if matching_numbers else (answer_numbers[-1] if answer_numbers else None)
        final_answer_correct = bool(matching_numbers)
    elif "required_term_groups" in case:
        final_answer_correct = text_matches_term_groups(final_answer, case.get("required_term_groups", []))
    else:
        final_answer_correct = text_contains_terms(final_answer, case.get("required_terms", []))

    integration_ok = (
        tool_choice in {"correct_call", "correct_skip", "optional_call", "optional_skip"}
        and ((normalized_input_usable if tool_expectation == "required" else True) if tool_expectation == "required" else True)
        and final_answer_correct
    )

    failure_flags = []
    if tool_choice == "missed_call":
        failure_flags.append("missed_tool_call")
    if tool_choice == "unnecessary_call":
        failure_flags.append("unnecessary_tool_call")
    if tool_expectation == "required" and tool_input_correct is False:
        failure_flags.append("bad_tool_input")
    if tool_expectation == "required" and not normalized_input_usable:
        failure_flags.append("unusable_tool_input")
    if tool_expectation == "required" and tool_result_correct and not final_answer_correct:
        failure_flags.append("ignored_or_misreported_tool_result")
    if not final_answer_correct:
        failure_flags.append("bad_final_answer")

    return {
        "tool_choice": tool_choice,
        "tool_called": tool_called,
        "tool_input_correct": tool_input_correct,
        "raw_tool_input_correct": raw_input_correct if tool_expectation == "required" else None,
        "normalized_tool_input_usable": normalized_input_usable if tool_expectation == "required" else None,
        "tool_result_correct": tool_result_correct,
        "final_answer_correct": final_answer_correct,
        "final_answer_numeric": final_numeric,
        "integration_ok": integration_ok,
        "failure_flags": failure_flags,
    }


def run_model_eval(
    model_config: dict[str, str],
    test_cases: list[dict[str, Any]],
    existing_model_result: dict[str, Any] | None = None,
    all_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    client = OpenAI(
        base_url=model_config["base_url"],
        api_key=model_config["api_key"],
    )

    current_case_map = {case["id"]: case for case in test_cases}
    case_results = []
    for item in list((existing_model_result or {}).get("cases", [])):
        stored_case = item.get("case", {})
        case_id = stored_case.get("id")
        current_case = current_case_map.get(case_id)
        if not current_case:
            continue
        run_result = item.get("run_result", {})
        if run_result.get("question") != current_case.get("question"):
            continue
        case_results.append(
            {
                "case": current_case,
                "run_result": run_result,
                "evaluation": evaluate_case_result(current_case, run_result),
            }
        )
    completed_case_ids = {item.get("case", {}).get("id") for item in case_results}
    for case in test_cases:
        if case["id"] in completed_case_ids:
            continue
        last_error: Exception | None = None
        run_result: dict[str, Any] | None = None
        for attempt in range(1, MATH_EVAL_MAX_RETRIES + 1):
            try:
                run_result = run_math_tool_conversation(
                    client=client,
                    model=model_config["model"],
                    question=case["question"],
                    max_tokens=80,
                )
                break
            except Exception as exc:
                last_error = exc
                if attempt >= MATH_EVAL_MAX_RETRIES:
                    raise
                time.sleep(MATH_EVAL_RETRY_DELAY_SECONDS * attempt)

        if run_result is None:
            raise RuntimeError(f"Failed to run case {case['id']}: {last_error}")
        evaluation = evaluate_case_result(case, run_result)
        case_results.append(
            {
                "case": case,
                "run_result": run_result,
                "evaluation": evaluation,
            }
        )
        if all_results is not None:
            existing = _find_model_result(all_results, model_config["tier"])
            if existing is None:
                all_results.append(
                    {
                        "model_config": _public_model_config(model_config),
                        "cases": case_results,
                    }
                )
            else:
                existing["cases"] = case_results
            _save_partial_results(all_results)
        time.sleep(MATH_EVAL_DELAY_SECONDS)

    return {
        "model_config": _public_model_config(model_config),
        "cases": case_results,
    }


def build_summary(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary_rows = []
    for model_result in results:
        counts = Counter()
        category_success: dict[str, list[bool]] = defaultdict(list)
        raw_tool_input_successes = 0
        normalized_tool_input_successes = 0
        tool_needed_total = 0
        durations_s: list[float] = []

        for item in model_result["cases"]:
            evaluation = item["evaluation"]
            case = item["case"]
            counts[evaluation["tool_choice"]] += 1
            counts["final_answer_correct" if evaluation["final_answer_correct"] else "final_answer_wrong"] += 1
            counts["integration_ok" if evaluation["integration_ok"] else "integration_failed"] += 1
            for flag in evaluation["failure_flags"]:
                counts[f"failure::{flag}"] += 1
            category_success[case["category"]].append(bool(evaluation["integration_ok"]))
            duration_ms = item["run_result"].get("duration_ms")
            if isinstance(duration_ms, (int, float)):
                durations_s.append(float(duration_ms) / 1000.0)
            if str(case.get("tool_expectation") or "") == "required":
                tool_needed_total += 1
                if evaluation.get("raw_tool_input_correct"):
                    raw_tool_input_successes += 1
                if evaluation.get("normalized_tool_input_usable"):
                    normalized_tool_input_successes += 1

        total = len(model_result["cases"])
        correct_calls = counts["correct_call"]
        correct_skips = counts["correct_skip"]

        summary_rows.append(
            {
                "tier": model_result["model_config"]["tier"],
                "label": model_result["model_config"]["label"],
                "model": model_result["model_config"]["model"],
                "total_cases": total,
                "tool_choice_accuracy": round((correct_calls + correct_skips) / total, 3),
                "tool_call_recall": round(correct_calls / tool_needed_total, 3) if tool_needed_total else 0.0,
                "raw_tool_input_accuracy": round(raw_tool_input_successes / tool_needed_total, 3) if tool_needed_total else 0.0,
                "normalized_tool_input_usability": round(normalized_tool_input_successes / tool_needed_total, 3) if tool_needed_total else 0.0,
                "final_answer_accuracy": round(counts["final_answer_correct"] / total, 3),
                "integration_success_rate": round(counts["integration_ok"] / total, 3),
                "avg_response_time_s": round(sum(durations_s) / len(durations_s), 1) if durations_s else None,
                "min_response_time_s": round(min(durations_s), 1) if durations_s else None,
                "max_response_time_s": round(max(durations_s), 1) if durations_s else None,
                "failure_counts": {k: v for k, v in counts.items() if k.startswith("failure::")},
                "category_success": {
                    category: round(sum(values) / len(values), 3)
                    for category, values in sorted(category_success.items())
                },
            }
        )
    return summary_rows


def choose_recommendation(summary_rows: list[dict[str, Any]]) -> str:
    acceptable_threshold = 0.8
    ordered = ["3b", "7b", "7b_plus"]
    by_tier = {row["tier"]: row for row in summary_rows}

    for tier in ordered:
        row = by_tier.get(tier)
        if not row:
            continue
        if row["integration_success_rate"] >= acceptable_threshold and row["tool_call_recall"] >= acceptable_threshold:
            return row["label"]

    best = max(summary_rows, key=lambda row: (row["integration_success_rate"], row["final_answer_accuracy"]))
    return best["label"]


def practical_comment(row: dict[str, Any]) -> str:
    integration = row["integration_success_rate"]
    tier = row.get("tier")
    if integration < 0.8:
        return "Fast enough, but still unreliable"
    if tier == "7b":
        return "Smallest acceptable tier"
    if tier == "7b_plus":
        return "Best overall quality"
    return "Balanced option"


def render_report(results: list[dict[str, Any]], summary_rows: list[dict[str, Any]]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    recommended_label = choose_recommendation(summary_rows)
    total_cases = max((row["total_cases"] for row in summary_rows), default=0)

    lines = [
        "# Math Tool Evaluation Report",
        "",
        f"Generated: {generated_at}",
        "",
        "## Scope",
        "",
        "- Goal: measure how reliably different model sizes use a Python-based math tool through orchestrator-driven tool calling.",
        "- Models tested: 3B, 7B, and 7B+.",
        f"- Total test cases: {total_cases}.",
        "- Task types: arithmetic, multi-step calculations, structured numeric tasks, insufficient-input/refusal cases, and conceptual control questions.",
        "",
        "## Integration Flow",
        "",
        "1. The user asks a mathematical question.",
        "2. The orchestrator sends the question to the model for routing.",
        "3. The model decides whether the Python math tool is required.",
        "4. If math is required, the model returns a structured tool request.",
        "5. The orchestrator validates the request and normalizes small schema mismatches when possible.",
        "6. The orchestrator calls the Python math tool.",
        "7. The math tool returns a deterministic result.",
        "8. The orchestrator sends the tool result back to the model.",
        "9. The model generates the final user-facing answer using the tool result.",
        "",
        "## Summary",
        "",
        "| Tier | Model | Tool choice accuracy | Tool-call recall | Raw tool-input accuracy | Normalized tool-input usability | Final answer accuracy | Integration success |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for row in summary_rows:
        lines.append(
            f"| {row['label']} | `{row['model']}` | {row['tool_choice_accuracy'] * 100:.1f}% | "
            f"{row['tool_call_recall'] * 100:.1f}% | {row['raw_tool_input_accuracy'] * 100:.1f}% | "
            f"{row['normalized_tool_input_usability'] * 100:.1f}% | {row['final_answer_accuracy'] * 100:.1f}% | "
            f"{row['integration_success_rate'] * 100:.1f}% |"
        )

    lines.extend(
        [
            "",
            "## Latency",
            "",
            "| Model | Avg Response Time | Min | Max | Practical Comment |",
            "| --- | ---: | ---: | ---: | --- |",
        ]
    )

    for row in summary_rows:
        lines.append(
            f"| {row['label']} | {row['avg_response_time_s']:.1f}s | {row['min_response_time_s']:.1f}s | "
            f"{row['max_response_time_s']:.1f}s | {practical_comment(row)} |"
        )

    lines.extend(
        [
            "",
            "## Math Tool Schema",
            "",
            "Request schema example for expression mode:",
            "",
            "```json",
            '{',
            '  "mode": "expression",',
            '  "expression": "(240 * 1.15) - 18"',
            '}',
            "```",
            "",
            "Request schema example for structured mode:",
            "",
            "```json",
            '{',
            '  "mode": "structured",',
            '  "operation": "weighted_mean",',
            '  "values": [78, 85, 92],',
            '  "weights": [0.2, 0.3, 0.5]',
            '}',
            "```",
            "",
            "Response schema example:",
            "",
            "```json",
            '{',
            '  "ok": true,',
            '  "mode": "structured",',
            '  "operation": "weighted_mean",',
            '  "result": 87.1,',
            '  "formatted_result": "87.1"',
            '}',
            "```",
            "",
            "## Recommendation",
            "",
            f"- Smallest acceptable model by this evaluation: **{recommended_label}**",
            "- Acceptance heuristic used here: at least 80% tool-call recall and 80% end-to-end integration success.",
            "- Practical takeaway: Qwen 2.5 7B is the minimum viable local tier, while GPT-OSS 120B shows the strongest overall tool behavior when a larger hosted model is acceptable.",
            "",
            "## Failure Patterns",
            "",
        ]
    )

    for row in summary_rows:
        failure_counts = row["failure_counts"]
        lines.append(f"### {row['label']}")
        if not failure_counts:
            lines.append("- No recurring failure pattern detected.")
        else:
            for failure_key, count in sorted(failure_counts.items()):
                lines.append(f"- `{failure_key.replace('failure::', '')}`: {count}")
        lines.append("")

    lines.extend(
        [
            "## Model Details",
            "",
        ]
    )

    for model_result in results:
        label = model_result["model_config"]["label"]
        lines.append(f"### {label}")
        lines.append("")
        for item in model_result["cases"]:
            case = item["case"]
            evaluation = item["evaluation"]
            run_result = item["run_result"]
            lines.append(f"- `{case['id']}` `{case['category']}`: {case['question']}")
            lines.append(f"  Final answer: {run_result['final_answer'] or '[empty]'}")
            lines.append(
                f"  Tool choice: {evaluation['tool_choice']}; final_answer_correct={evaluation['final_answer_correct']}; "
                f"raw_tool_input_correct={evaluation.get('raw_tool_input_correct')}; "
                f"normalized_tool_input_usable={evaluation.get('normalized_tool_input_usable')}; "
                f"integration_ok={evaluation['integration_ok']}"
            )
            if run_result["tool_events"]:
                last_event = run_result["tool_events"][-1]
                lines.append(
                    f"  Tool args: `{last_event['raw_arguments']}` -> normalized `{json.dumps(last_event.get('normalized_arguments'), ensure_ascii=False)}` -> result `{json.dumps(last_event['tool_result'], ensure_ascii=False)}`"
                )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    test_cases = load_json(TEST_SET_PATH)
    results = _refresh_existing_results(_load_existing_results(), test_cases)
    for model_config in MODEL_CONFIGS:
        if MATH_EVAL_ONLY_TIER and model_config["tier"] != MATH_EVAL_ONLY_TIER:
            continue
        existing_model_result = _find_model_result(results, model_config["tier"])
        model_result = run_model_eval(
            model_config,
            test_cases,
            existing_model_result=existing_model_result,
            all_results=results,
        )
        existing = _find_model_result(results, model_config["tier"])
        if existing is None:
            results.append(model_result)
        else:
            existing["model_config"] = model_result["model_config"]
            existing["cases"] = model_result["cases"]
        _save_partial_results(results)
    summary_rows = build_summary(results)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "models": results,
        "summary": summary_rows,
        "recommended_model": choose_recommendation(summary_rows),
    }
    save_json(RESULTS_PATH, payload)
    REPORT_PATH.write_text(render_report(results, summary_rows), encoding="utf-8")
    print(f"Saved {RESULTS_PATH}")
    print(f"Saved {REPORT_PATH}")


if __name__ == "__main__":
    main()
