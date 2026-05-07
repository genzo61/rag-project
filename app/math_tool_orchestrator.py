from __future__ import annotations

import json
from time import perf_counter
from typing import Any, cast

from openai import OpenAI

from .math_tool import (
    normalize_python_math_tool_arguments,
    PYTHON_MATH_TOOL_NAME,
    PYTHON_MATH_TOOL_SCHEMA,
    run_python_math_tool,
    validate_python_math_tool_arguments,
)

MATH_TOOL_SYSTEM_PROMPT = """You are a math assistant with access to one exact Python math tool.

Rules:
- Use the tool for any exact arithmetic, percentage, average, median, weighted mean, threshold count, or multi-step numeric task.
- Do not do mental math when the user is asking for a computed result.
- Use mode="expression" for free-form arithmetic expressions.
- Use mode="structured" for named operations like mean, weighted_mean, percentage_change, percentage_of, count_greater_than, median, or sum.
- For purely conceptual math questions that do not require calculation, answer directly without using the tool.
- After a tool result is returned, use that result in the final answer and do not contradict it.
- Keep the final answer concise and include the numeric result clearly when one was computed.
- If the user asks for a formula, give the formula directly in symbolic form first.
- Do not add source lists, tool boilerplate, or extra process narration in the final answer.
"""


def _tool_call_to_message_payload(tool_call: Any) -> dict[str, Any]:
    return {
        "id": tool_call.id,
        "type": "function",
        "function": {
            "name": tool_call.function.name,
            "arguments": tool_call.function.arguments,
        },
    }


def run_math_tool_conversation(
    client: OpenAI,
    model: str,
    question: str,
    max_rounds: int = 3,
    max_tokens: int = 160,
) -> dict[str, Any]:
    started_at = perf_counter()
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": MATH_TOOL_SYSTEM_PROMPT},
        {"role": "user", "content": question},
    ]
    tool_events: list[dict[str, Any]] = []
    final_answer = ""
    raw_responses: list[dict[str, Any]] = []

    for round_index in range(max_rounds):
        response = client.chat.completions.create(
            model=model,
            messages=cast(Any, messages),
            tools=[cast(Any, PYTHON_MATH_TOOL_SCHEMA)],
            tool_choice="auto",
            temperature=0.0,
            max_tokens=max_tokens,
        )

        message = response.choices[0].message
        tool_calls = list(getattr(message, "tool_calls", []) or [])
        raw_responses.append(
            {
                "round": round_index + 1,
                "content": message.content or "",
                "tool_call_count": len(tool_calls),
            }
        )

        assistant_payload: dict[str, Any] = {
            "role": "assistant",
            "content": message.content or "",
        }

        if tool_calls:
            assistant_payload["tool_calls"] = [
                _tool_call_to_message_payload(tool_call) for tool_call in tool_calls
            ]

        messages.append(assistant_payload)

        if not tool_calls:
            final_answer = message.content or ""
            break

        for tool_call in tool_calls:
            tool_name = tool_call.function.name
            raw_arguments = tool_call.function.arguments or "{}"
            normalized_arguments: dict[str, Any] = {}
            raw_validation: dict[str, Any] = {"ok": False, "error": "arguments not parsed"}
            validation: dict[str, Any] = {"ok": False, "error": "arguments not parsed"}

            try:
                parsed_arguments = json.loads(raw_arguments)
            except Exception as exc:
                parsed_arguments = {}
                tool_result = {
                    "ok": False,
                    "error": f"Invalid JSON tool arguments: {exc}",
                }
            else:
                if tool_name != PYTHON_MATH_TOOL_NAME:
                    tool_result = {
                        "ok": False,
                        "error": f"Unsupported tool: {tool_name}",
                    }
                    normalized_arguments = parsed_arguments
                    raw_validation = {"ok": True}
                    validation = {"ok": True}
                else:
                    normalized_arguments = normalize_python_math_tool_arguments(parsed_arguments)
                    raw_validation = validate_python_math_tool_arguments(parsed_arguments)
                    validation = validate_python_math_tool_arguments(normalized_arguments)
                    if not validation.get("ok"):
                        tool_result = {
                            "ok": False,
                            "error": validation.get("error", "invalid tool arguments"),
                        }
                    else:
                        tool_result = run_python_math_tool(normalized_arguments)

            tool_events.append(
                {
                    "tool_name": tool_name,
                    "raw_arguments": raw_arguments,
                    "parsed_arguments": parsed_arguments,
                    "normalized_arguments": normalized_arguments if tool_name == PYTHON_MATH_TOOL_NAME else parsed_arguments,
                    "raw_validation": raw_validation if tool_name == PYTHON_MATH_TOOL_NAME else {"ok": True},
                    "normalized_validation": validation if tool_name == PYTHON_MATH_TOOL_NAME else {"ok": True},
                    "tool_result": tool_result,
                }
            )

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )

    return {
        "question": question,
        "model": model,
        "tool_called": bool(tool_events),
        "tool_events": tool_events,
        "final_answer": final_answer.strip(),
        "raw_responses": raw_responses,
        "duration_ms": round((perf_counter() - started_at) * 1000, 1),
    }
