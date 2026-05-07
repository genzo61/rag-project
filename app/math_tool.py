from __future__ import annotations

import ast
import math
import statistics
from typing import Any

PYTHON_MATH_TOOL_NAME = "python_math_tool"

PYTHON_MATH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": PYTHON_MATH_TOOL_NAME,
        "description": (
            "Use this tool for exact mathematical work. "
            "Call it for arithmetic, multi-step calculations, averages, percentages, "
            "medians, weighted means, counts over a threshold, or any task where the "
            "user needs an exact numeric result. Do not use it for purely conceptual "
            "questions that can be answered without calculation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["expression", "structured"],
                    "description": "Use expression for free-form arithmetic, structured for named numeric operations.",
                },
                "expression": {
                    "type": "string",
                    "description": (
                        "A pure arithmetic Python-style expression such as "
                        "'(18.75 * 4) + 12.5' or '(180 + 120) / ((180 / 60) + (120 / 80))'."
                    ),
                },
                "operation": {
                    "type": "string",
                    "enum": [
                        "mean",
                        "weighted_mean",
                        "percentage_change",
                        "percentage_of",
                        "count_greater_than",
                        "median",
                        "sum",
                    ],
                    "description": "Named structured operation.",
                },
                "numbers": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Input number list for mean, median, or sum.",
                },
                "values": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Input values for weighted mean.",
                },
                "weights": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Weight list for weighted mean.",
                },
                "old_value": {
                    "type": "number",
                    "description": "Original value for percentage_change.",
                },
                "new_value": {
                    "type": "number",
                    "description": "New value for percentage_change.",
                },
                "value": {
                    "type": "number",
                    "description": "Base value for percentage_of.",
                },
                "percent": {
                    "type": "number",
                    "description": "Percent value for percentage_of.",
                },
                "threshold": {
                    "type": "number",
                    "description": "Threshold for count_greater_than.",
                },
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
    },
}

ALLOWED_CONSTANTS = {
    "pi": math.pi,
    "e": math.e,
}

ALLOWED_BINARY_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.Pow: lambda a, b: a**b,
    ast.Mod: lambda a, b: a % b,
}

ALLOWED_UNARY_OPS = {
    ast.UAdd: lambda a: +a,
    ast.USub: lambda a: -a,
}


def _format_number(value: float) -> str:
    if math.isfinite(value) and float(value).is_integer():
        return str(int(value))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _safe_eval_expression(expression: str) -> float:
    tree = ast.parse(expression, mode="eval")

    def _eval_node(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval_node(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in ALLOWED_CONSTANTS:
            return float(ALLOWED_CONSTANTS[node.id])
        if isinstance(node, ast.BinOp) and type(node.op) in ALLOWED_BINARY_OPS:
            left = _eval_node(node.left)
            right = _eval_node(node.right)
            return float(ALLOWED_BINARY_OPS[type(node.op)](left, right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in ALLOWED_UNARY_OPS:
            operand = _eval_node(node.operand)
            return float(ALLOWED_UNARY_OPS[type(node.op)](operand))
        raise ValueError(f"Unsupported expression node: {type(node).__name__}")

    return _eval_node(tree)


def _float_list(values: Any, field_name: str) -> list[float]:
    if not isinstance(values, list) or not values:
        raise ValueError(f"{field_name} must be a non-empty number list")
    converted = []
    for item in values:
        if not isinstance(item, (int, float)):
            raise ValueError(f"{field_name} must contain only numbers")
        converted.append(float(item))
    return converted


def normalize_python_math_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(arguments or {})

    mode = str(normalized.get("mode") or "").strip().lower()
    operation = str(normalized.get("operation") or "").strip().lower()
    expression = str(normalized.get("expression") or "").strip()
    value_expression = str(normalized.get("value") or "").strip()

    if not expression and value_expression:
        normalized["expression"] = value_expression
        expression = value_expression

    operation_names = {
        "mean",
        "weighted_mean",
        "percentage_change",
        "percentage_of",
        "count_greater_than",
        "median",
        "sum",
    }

    if mode in operation_names and not operation:
        normalized["operation"] = mode
        normalized["mode"] = "structured"
        operation = mode
        mode = "structured"

    if not mode:
        if expression:
            normalized["mode"] = "expression"
        elif operation:
            normalized["mode"] = "structured"

    if not operation and normalized.get("mode") == "structured":
        if "weights" in normalized and "values" in normalized:
            normalized["operation"] = "weighted_mean"
        elif "old_value" in normalized and "new_value" in normalized:
            normalized["operation"] = "percentage_change"
        elif "value" in normalized and "percent" in normalized:
            normalized["operation"] = "percentage_of"
        elif "threshold" in normalized and ("numbers" in normalized or "values" in normalized):
            normalized["operation"] = "count_greater_than"
        operation = str(normalized.get("operation") or "").strip().lower()

    if operation in {"mean", "median", "sum", "count_greater_than"}:
        if "numbers" not in normalized and "values" in normalized:
            normalized["numbers"] = normalized["values"]

    return normalized


def validate_python_math_tool_arguments(arguments: dict[str, Any]) -> dict[str, Any]:
    mode = str(arguments.get("mode") or "").strip().lower()
    if mode not in {"expression", "structured"}:
        return {"ok": False, "error": "mode must be either 'expression' or 'structured'"}

    if mode == "expression":
        expression = str(arguments.get("expression") or "").strip()
        if not expression:
            return {"ok": False, "error": "expression is required when mode='expression'"}
        return {"ok": True}

    operation = str(arguments.get("operation") or "").strip().lower()
    if not operation:
        return {"ok": False, "error": "operation is required when mode='structured'"}

    required_fields = {
        "mean": ("numbers",),
        "weighted_mean": ("values", "weights"),
        "percentage_change": ("old_value", "new_value"),
        "percentage_of": ("value", "percent"),
        "count_greater_than": ("numbers", "threshold"),
        "median": ("numbers",),
        "sum": ("numbers",),
    }

    if operation not in required_fields:
        return {"ok": False, "error": f"Unsupported structured operation: {operation}"}

    missing = [field for field in required_fields[operation] if field not in arguments]
    if missing:
        return {"ok": False, "error": f"Missing required fields for {operation}: {', '.join(missing)}"}

    return {"ok": True}


def run_python_math_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    mode = str(arguments.get("mode") or "").strip().lower()
    try:
        if mode == "expression":
            expression = str(arguments.get("expression") or "").strip()
            if not expression:
                raise ValueError("expression is required when mode='expression'")
            result = _safe_eval_expression(expression)
            return {
                "ok": True,
                "mode": mode,
                "result": result,
                "formatted_result": _format_number(result),
                "explanation": f"Evaluated expression: {expression}",
            }

        if mode == "structured":
            operation = str(arguments.get("operation") or "").strip().lower()

            if operation == "mean":
                numbers = _float_list(arguments.get("numbers"), "numbers")
                result = sum(numbers) / len(numbers)
            elif operation == "weighted_mean":
                values = _float_list(arguments.get("values"), "values")
                weights = _float_list(arguments.get("weights"), "weights")
                if len(values) != len(weights):
                    raise ValueError("values and weights must have the same length")
                total_weight = sum(weights)
                if total_weight == 0:
                    raise ValueError("weights must not sum to zero")
                result = sum(v * w for v, w in zip(values, weights)) / total_weight
            elif operation == "percentage_change":
                old_value = float(arguments["old_value"])
                new_value = float(arguments["new_value"])
                if old_value == 0:
                    raise ValueError("old_value must not be zero for percentage_change")
                result = ((new_value - old_value) / old_value) * 100.0
            elif operation == "percentage_of":
                value = float(arguments["value"])
                percent = float(arguments["percent"])
                result = value * (percent / 100.0)
            elif operation == "count_greater_than":
                numbers = _float_list(arguments.get("numbers"), "numbers")
                threshold = float(arguments["threshold"])
                result = float(sum(1 for number in numbers if number > threshold))
            elif operation == "median":
                numbers = _float_list(arguments.get("numbers"), "numbers")
                result = float(statistics.median(numbers))
            elif operation == "sum":
                numbers = _float_list(arguments.get("numbers"), "numbers")
                result = sum(numbers)
            else:
                raise ValueError(f"Unsupported structured operation: {operation}")

            return {
                "ok": True,
                "mode": mode,
                "operation": operation,
                "result": result,
                "formatted_result": _format_number(result),
            }

        raise ValueError("mode must be either 'expression' or 'structured'")
    except Exception as exc:
        return {
            "ok": False,
            "mode": mode or "unknown",
            "error": str(exc),
        }
