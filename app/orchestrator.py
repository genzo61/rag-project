import json
import os
import re
import logging
from time import perf_counter
from typing import Any, cast


from .db import count_documents
from .dp_db import build_dp_db_context, detect_internal_data_domains, query_internal_data
from .rag import (
    PRIMARY_LLM_MODEL,
    _build_model_candidates,
    _public_web_results,
    _rerank_web_results,
    build_web_context,
    clean_answer,
    client,
    create_chat_completion,
    retrieve_context,
    web_search,
)
from .math_tool import run_python_math_tool
from .math_tool_orchestrator import run_math_tool_conversation, run_math_tool_via_json_plan

logger = logging.getLogger("rag.orchestrator")

PUBLIC_MODEL_ID = (os.getenv("LOCAL_CHAT_MODEL_ID", "") or PRIMARY_LLM_MODEL or "local-rag").strip()

DP_DB_KEYWORDS = (
    "audit",
    "history",
    "hidden",
    "metadata",
    "processing failure",
    "failure",
    "validation",
    "cross-reference",
    "cross reference",
    "internal",
    "join",
    "owner",
    "status",
    "npm package",
    "package",
    "audit history",
    "hidden metadata",
    "processing failures",
    "validation results",
)
ROUTING_STRONG_VECTOR_THRESHOLD = 0.32
ROUTING_MIN_VECTOR_THRESHOLD = 0.18
ROUTING_GUIDANCE_SOURCE = "dp-assistant-demo"

def _extract_known_package_name(question: str) -> str | None:
    q = (question or "").lower()

    quoted = re.search(r"""['"]([@a-z0-9][@a-z0-9._/\-]{0,80})['"]""", q, flags=re.IGNORECASE)
    if quoted:
        return quoted.group(1).strip().lower()

    patterns = (
        r"\bnpm package\s+([@a-z0-9][@a-z0-9._/\-]{0,80})\b",
        r"\bpackage\s+([@a-z0-9][@a-z0-9._/\-]{0,80})\b",
        r"\b([@a-z0-9][@a-z0-9._/\-]{0,80})\s+on npm\b",
        r"\b([@a-z0-9][@a-z0-9._/\-]{0,80})\s+npm\b",
    )

    for pattern in patterns:
        match = re.search(pattern, q, flags=re.IGNORECASE)
        if match:
            return match.group(1).strip().lower()

    return None


PACKAGE_HINTS = (
    "npm",
    "package",
    "release",
    "version",
    "published",
    "npmjs",
    "left-pad",
    "leftpad",
    "lodash",
    "event-stream",
    "is-number",
)

EXPLICIT_WEB_PATTERNS = (
    "search on web",
    "search the web",
    "search web",
    "use web",
    "from web",
    "on the web",
    "web search",
    "search online",
    "look it up online",
    "look it up on the web",
    "internette ara",
    "webde ara",
    "webden bul",
)

GENERAL_MATH_FORMULA_TERMS = (
    "arithmetic mean",
    "aritmetic mean",
    "average formula",
    "mean formula",
    "geometric mean",
    "harmonic mean",
    "weighted mean",
    "median formula",
    "mode formula",
    "formula",
    "formül",
    "formul",
    "equation",
    "denklem",
    "area",
    "alan",
    "perimeter",
    "çevre",
    "cevre",
    "circle",
    "daire",
    "triangle",
    "üçgen",
    "ucgen",
    "rectangle",
    "dikdörtgen",
    "dikdortgen",
    "derivative",
    "türev",
    "turev",
    "integral",
)

GENERAL_MATH_TASK_TERMS = (
    "calculate",
    "compute",
    "solve",
    "sum",
    "average",
    "mean",
    "median",
    "weighted mean",
    "percentage",
    "percent",
    "ratio",
    "difference",
    "divide",
    "multiply",
    "plus",
    "minus",
    "total",
    "hesapla",
    "çöz",
    "coz",
    "topla",
    "çıkar",
    "cikar",
    "böl",
    "bol",
    "çarp",
    "carp",
    "ortalama",
    "aritmetik ortalama",
    "medyan",
    "yüzde",
    "yuzde",
    "oran",
    "fark",
    "toplam",
)

MATH_EXCLUSION_TERMS = (
    "package",
    "npm",
    "cve",
    "github",
    "validation result",
    "audit history",
    "processing job",
    "water main",
    "crli",
    "ili",
)

MATH_ROUTER_SYSTEM_PROMPT = """You are a routing model inside an orchestrator.

Decide whether a Python math tool is required for the user's question.

Return strict JSON with keys:
- use_math_tool: boolean
- reason: short string

Use the math tool when the user needs exact arithmetic, symbolic math formulas, percentages, averages, medians, weighted means, multi-step calculations, or deterministic numeric computation.
Do not use the math tool for package/version lookup, document retrieval, internal audit questions, or ordinary RAG/web-search questions.

Examples:
- "What is 125 + 349?" -> use_math_tool=true
- "Calculate (18.75 * 4) + 12.5." -> use_math_tool=true
- "Find the arithmetic mean of 12, 18, 24, and 30." -> use_math_tool=true
- "What is the latest npm version of left-pad?" -> use_math_tool=false
"""


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in phrases)


def _question_prefers_turkish(question: str) -> bool:
    raw = question or ""
    lowered = raw.lower()
    if any(ch in raw for ch in "çğıİöşüÇĞIÖŞÜ"):
        return True

    turkish_signals = (
        " nasıl",
        " nedir",
        " hangi",
        " hangileri",
        " kaç",
        " göster",
        " listele",
        " var mı",
        " var mi",
        " en son",
        " bugün",
        " yarın",
        " saat",
        " tarih",
        " için",
        " kural",
        " formül",
        " formul",
    )
    return any(token in lowered for token in turkish_signals)


def _answer_style_instructions(question: str) -> str:
    prefers_turkish = _question_prefers_turkish(question)
    language_line = (
        "Answer in Turkish because the user's question is in Turkish.\n"
        if prefers_turkish
        else "Answer in the same language as the user's question.\n"
    )
    return (
        language_line
        + "Use natural, user-friendly wording.\n"
        + "Lead with the direct answer, not the tool or source narration.\n"
        + "Do not output raw database rows, key=value dumps, or internal field names unless the user explicitly asks for technical detail.\n"
        + "Do not mention internal ids, rule_id values, formula_id values, or timestamps unless the user explicitly asks for them or they are required to disambiguate the answer.\n"
        + "If the user asks 'which one' or 'which ones', prefer names and short descriptions over ids and raw metadata.\n"
        + "When multiple records exist, group or summarize them in readable bullets instead of listing every column.\n"
        + "Keep the answer concise, clear, and easy to scan.\n"
    )


def _question_requests_ids(question: str) -> bool:
    q = (question or "").lower()
    if re.search(r"\b[a-z_]*_id\b", q):
        return True
    if re.search(r"\bids?\b", q):
        return True
    return any(
        token in q
        for token in (
            "identifier",
            "identifiers",
            "kimlik",
            "kimlikler",
            "id'si",
            "idsi",
            "idleri",
            "numarasi",
            "numarası",
        )
    )


def _question_requests_timestamps(question: str) -> bool:
    q = (question or "").lower()
    return any(
        token in q
        for token in (
            "timestamp",
            "timestamps",
            "time",
            "times",
            "date",
            "dates",
            "dated",
            "when",
            "started at",
            "completed at",
            "created at",
            "updated at",
            "computed at",
            "window start",
            "window end",
            "ne zaman",
            "tarih",
            "tarihi",
            "zaman",
            "saat",
            "başlangıç",
            "baslangic",
            "bitiş",
            "bitis",
            "oluşturul",
            "olusturul",
            "güncellen",
            "guncellen",
            "hesaplan",
        )
    )


def _explicitly_requests_web(question: str) -> bool:
    return _contains_any(question, EXPLICIT_WEB_PATTERNS)


def _is_general_math_formula_query(question: str) -> bool:
    q = (question or "").lower()
    asks_math_term = any(term in q for term in GENERAL_MATH_FORMULA_TERMS)
    asks_how = any(
        token in q
        for token in (
            "how",
            "what",
            "nedir",
            "nasıl",
            "nasil",
            "formula",
            "formül",
            "formul",
            "calculate",
            "find",
            "hesapla",
            "bul",
            "çöz",
            "coz",
        )
    )
    asks_internal = any(
        token in q
        for token in (
            "audit",
            "metadata",
            "validation",
            "snapshot",
            "formula variable",
            "bulk formula",
            "job",
            "jobs",
            "processing",
            "internal",
            "dp db",
        )
    )
    return asks_math_term and asks_how and not asks_internal


def _is_math_tool_candidate(question: str) -> bool:
    q = (question or "").lower().strip()
    if not q:
        return False

    if _extract_known_package_name(question):
        return False

    if any(token in q for token in MATH_EXCLUSION_TERMS):
        return False

    if _is_general_math_formula_query(question):
        return True

    has_math_symbols = bool(
        re.search(r"\d", q)
        and re.search(r"[\+\-\*/%=()^×÷]", q)
    )
    has_equation_shape = bool(re.search(r"\b[a-z]\s*=", q) or re.search(r"\d\s*[a-z]\b", q))
    has_percent_problem = bool(re.search(r"\d+(?:[.,]\d+)?\s*%", q))
    has_multiple_numbers = len(re.findall(r"-?\d+(?:[.,]\d+)?", q)) >= 2
    has_math_language = any(term in q for term in GENERAL_MATH_TASK_TERMS)
    has_percent_language = any(term in q for term in ("percent", "percentage", "yüzde", "yuzde"))
    return (
        has_math_symbols
        or has_equation_shape
        or has_percent_problem
        or (has_percent_language and has_multiple_numbers)
        or (has_math_language and has_multiple_numbers)
    )


def _parse_router_json(text: str) -> dict[str, Any] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    try:
        return json.loads(raw)
    except Exception:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None


def _route_question_for_math_tool(question: str) -> dict[str, Any]:
    last_error: Exception | None = None

    for model_name in _build_model_candidates():
        try:
            response = create_chat_completion(
                model=model_name,
                messages=cast(
                    Any,
                    [
                        {"role": "system", "content": MATH_ROUTER_SYSTEM_PROMPT},
                        {"role": "user", "content": question},
                    ],
                ),
                temperature=0.0,
                max_tokens=80,
            )
            content = response.choices[0].message.content or ""
            parsed = _parse_router_json(content)
            if not parsed or "use_math_tool" not in parsed:
                raise ValueError(f"Invalid router JSON: {content}")

            route_decision = bool(parsed.get("use_math_tool"))
            route_reason = str(parsed.get("reason") or "").strip()
            if not route_decision and _is_math_tool_candidate(question):
                route_decision = True
                route_reason = "validated math route override"

            return {
                "ok": True,
                "model_used": model_name,
                "use_math_tool": route_decision,
                "reason": route_reason,
                "raw_content": content,
                "fallback_used": route_reason == "validated math route override",
            }
        except Exception as exc:
            last_error = exc
            logger.warning(
                "orchestrator_math_router_failed model=%s error=%s",
                model_name,
                exc,
            )

    fallback_decision = _is_math_tool_candidate(question)
    return {
        "ok": False,
        "model_used": PRIMARY_LLM_MODEL,
        "use_math_tool": fallback_decision,
        "reason": "fallback heuristic after routing failure",
        "raw_content": "",
        "fallback_used": True,
        "error": str(last_error) if last_error else "unknown router error",
    }


def _numbers_from_question(question: str) -> list[float]:
    numbers = []
    for raw in re.findall(r"-?\d+(?:[.,]\d+)?", question or ""):
        try:
            numbers.append(float(raw.replace(",", ".")))
        except ValueError:
            continue
    return numbers


TURKISH_NUMBER_WORDS = {
    "sifir": 0,
    "bir": 1,
    "iki": 2,
    "uc": 3,
    "dort": 4,
    "bes": 5,
    "alti": 6,
    "yedi": 7,
    "sekiz": 8,
    "dokuz": 9,
    "on": 10,
    "yirmi": 20,
    "otuz": 30,
    "kirk": 40,
    "elli": 50,
    "altmis": 60,
    "yetmis": 70,
    "seksen": 80,
    "doksan": 90,
    "yuz": 100,
}


def _normalize_turkish_text(text: str) -> str:
    return (text or "").lower().translate(
        str.maketrans(
            {
                "\u00e7": "c",
                "\u011f": "g",
                "\u0131": "i",
                "\u00f6": "o",
                "\u015f": "s",
                "\u00fc": "u",
            }
        )
    )


def _parse_turkish_number_phrase(phrase: str) -> float | None:
    tokens = [token for token in re.findall(r"[a-z]+", _normalize_turkish_text(phrase)) if token]
    if not tokens:
        return None

    total = 0
    current = 0
    matched = False
    for token in tokens:
        if token not in TURKISH_NUMBER_WORDS:
            return None
        matched = True
        value = TURKISH_NUMBER_WORDS[token]
        if value == 100:
            current = max(current, 1) * 100
        elif value >= 10:
            current += value
        else:
            current += value

    if not matched:
        return None
    total += current
    return float(total)


def _format_math_expression_number(value: float) -> str:
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.10f}".rstrip("0").rstrip(".")


def _question_uses_turkish_number_words(question: str) -> bool:
    normalized = _normalize_turkish_text(question)
    tokens = set(re.findall(r"[a-z]+", normalized))
    return bool(tokens & set(TURKISH_NUMBER_WORDS.keys()))


def _integer_to_turkish_words(value: int) -> str:
    ones = {
        0: "sifir",
        1: "bir",
        2: "iki",
        3: "uc",
        4: "dort",
        5: "bes",
        6: "alti",
        7: "yedi",
        8: "sekiz",
        9: "dokuz",
    }
    tens = {
        10: "on",
        20: "yirmi",
        30: "otuz",
        40: "kirk",
        50: "elli",
        60: "altmis",
        70: "yetmis",
        80: "seksen",
        90: "doksan",
    }

    if value == 0:
        return ones[0]
    if value < 0:
        return f"eksi {_integer_to_turkish_words(abs(value))}"

    def under_thousand(number: int) -> str:
        parts: list[str] = []
        hundreds = number // 100
        remainder = number % 100
        if hundreds:
            if hundreds > 1:
                parts.append(ones[hundreds])
            parts.append("yuz")
        if remainder >= 10:
            tens_value = (remainder // 10) * 10
            if tens_value:
                parts.append(tens[tens_value])
            remainder = remainder % 10
        if remainder:
            parts.append(ones[remainder])
        return " ".join(parts)

    chunks = [
        (1_000_000_000, "milyar"),
        (1_000_000, "milyon"),
        (1_000, "bin"),
    ]
    parts: list[str] = []
    remaining = value
    for divisor, label in chunks:
        chunk = remaining // divisor
        if not chunk:
            continue
        if divisor == 1_000 and chunk == 1:
            parts.append(label)
        else:
            parts.append(f"{under_thousand(chunk)} {label}".strip())
        remaining %= divisor
    if remaining:
        parts.append(under_thousand(remaining))
    return " ".join(part for part in parts if part).strip()


def _format_math_answer_for_user(question: str, result: dict[str, Any]) -> str:
    formatted = str(result.get("formatted_result") or result.get("result") or "").strip()
    raw_result = result.get("result")
    if not formatted:
        return formatted

    if (
        _question_prefers_turkish(question)
        and _question_uses_turkish_number_words(question)
        and isinstance(raw_result, (int, float))
        and float(raw_result).is_integer()
    ):
        integer_value = int(raw_result)
        return f"{_integer_to_turkish_words(integer_value)} ({formatted})"

    return formatted


def _extract_turkish_word_expression(question: str) -> str | None:
    normalized = _normalize_turkish_text(question)
    normalized = re.sub(r"\bisleminin\b|\bislemi\b|\bsonucu\b|\bkactir\b|\bkac\b|\bnedir\b|\bne\b", " ", normalized)
    normalized = re.sub(r"[?.,!]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return None

    operator_aliases = {
        "arti": "+",
        "topla": "+",
        "eksi": "-",
        "cikar": "-",
        "carpi": "*",
        "kere": "*",
        "bolu": "/",
    }
    operator_pattern = r"\b(" + "|".join(re.escape(key) for key in operator_aliases) + r")\b"
    parts = re.split(operator_pattern, normalized)
    if len(parts) < 3:
        return None

    expression_parts: list[str] = []
    expect_number = True
    for part in parts:
        token = part.strip()
        if not token:
            continue
        if token in operator_aliases:
            if expect_number or not expression_parts:
                return None
            expression_parts.append(operator_aliases[token])
            expect_number = True
            continue

        number_value = _parse_turkish_number_phrase(token)
        if number_value is None:
            return None
        expression_parts.append(_format_math_expression_number(number_value))
        expect_number = False

    if expect_number or len(expression_parts) < 3:
        return None
    return "".join(expression_parts)


def _extract_arithmetic_expression(question: str) -> str | None:
    normalized = (
        (question or "")
        .replace("×", "*")
        .replace("÷", "/")
        .replace("^", "**")
    )
    candidates = re.findall(r"[-+*/().\d\s*]+", normalized)
    candidates = [
        re.sub(r"\s+", "", candidate)
        for candidate in candidates
        if re.search(r"\d", candidate) and re.search(r"[+\-*/]", candidate)
    ]
    if not candidates:
        return _extract_turkish_word_expression(question)
    return max(candidates, key=len).strip()


def _direct_math_tool_result(question: str) -> dict[str, Any] | None:
    q = (question or "").lower()

    expression = _extract_arithmetic_expression(question)
    if expression:
        result = run_python_math_tool(
            {
                "mode": "expression",
                "expression": expression,
            }
        )
        if result.get("ok"):
            return {
                "answer": _format_math_answer_for_user(question, result),
                "tool_event": {
                    "tool_name": "python_math_tool",
                    "normalized_arguments": {
                        "mode": "expression",
                        "expression": expression,
                    },
                    "tool_result": result,
                    "fallback": "direct_expression",
                },
            }

    numbers = _numbers_from_question(question)
    operation = None
    arguments: dict[str, Any] = {"mode": "structured"}

    if any(term in q for term in ("average", "mean", "ortalama", "aritmetik ortalama")) and numbers:
        operation = "mean"
        arguments["numbers"] = numbers
    elif any(term in q for term in ("median", "medyan")) and numbers:
        operation = "median"
        arguments["numbers"] = numbers
    elif any(term in q for term in ("sum", "total", "toplam", "topla")) and numbers:
        operation = "sum"
        arguments["numbers"] = numbers
    elif re.search(r"\d+(?:[.,]\d+)?\s*%\s*(?:of|of the|si|sı|i|ı)?", q) and len(numbers) >= 2:
        operation = "percentage_of"
        arguments["percent"] = numbers[0]
        arguments["value"] = numbers[1]
    elif any(term in q for term in ("percent of", "percentage of")) and len(numbers) >= 2:
        operation = "percentage_of"
        arguments["percent"] = numbers[0]
        arguments["value"] = numbers[1]
    elif any(term in q for term in ("yüzde", "yuzde")) and len(numbers) >= 2:
        operation = "percentage_of"
        arguments["value"] = numbers[0]
        arguments["percent"] = numbers[1]
    elif any(term in q for term in ("percentage change", "yüzde değişim", "yuzde degisim")) and len(numbers) >= 2:
        operation = "percentage_change"
        arguments["old_value"] = numbers[0]
        arguments["new_value"] = numbers[1]

    if not operation:
        return None

    arguments["operation"] = operation
    result = run_python_math_tool(arguments)
    if not result.get("ok"):
        return None

    return {
        "answer": _format_math_answer_for_user(question, result),
        "tool_event": {
            "tool_name": "python_math_tool",
            "normalized_arguments": arguments,
            "tool_result": result,
            "fallback": "direct_structured",
        },
    }


def _answer_with_math_tool(question: str, route_info: dict[str, Any]) -> dict[str, Any]:
    direct_result = _direct_math_tool_result(question)
    if direct_result:
        return {
            "question": question,
            "answer": direct_result["answer"],
            "sources_used": ["math_tool"],
            "vector_queried_first": False,
            "model_used": PUBLIC_MODEL_ID,
            "tool_trace": [
                {
                    "order": 1,
                    "tool": "math_router",
                    "used": True,
                    "result_count": 1,
                    "decision": route_info.get("use_math_tool"),
                    "reason": route_info.get("reason"),
                },
                {
                    "order": 2,
                    "tool": "python_math_tool",
                    "used": True,
                    "tool_called": True,
                    "result_count": 1,
                    "fallback": direct_result["tool_event"].get("fallback"),
                },
            ],
            "retrieved_chunks": [],
            "dp_db_results": [],
            "web_sources": [],
            "math_tool_trace": [direct_result["tool_event"]],
            "duration_ms": None,
        }

    last_error: Exception | None = None

    for model_name in _build_model_candidates():
        try:
            math_result = run_math_tool_conversation(
                client=client,
                model=model_name,
                question=question,
            )
            tool_called = bool(math_result.get("tool_called"))
            tool_events = math_result.get("tool_events", [])
            answer = (math_result.get("final_answer") or "").strip()

            if not answer and tool_called and tool_events:
                last_tool_result = tool_events[-1].get("tool_result", {})
                if last_tool_result.get("ok"):
                    answer = str(last_tool_result.get("formatted_result") or last_tool_result.get("result") or "").strip()

            if not answer:
                direct_result = _direct_math_tool_result(question)
                if direct_result:
                    answer = direct_result["answer"]
                    tool_called = True
                    tool_events = [direct_result["tool_event"]]

            return {
                "question": question,
                "answer": answer or "I could not produce a math answer.",
                "sources_used": ["math_tool"] if tool_called else [],
                "vector_queried_first": False,
                "model_used": PUBLIC_MODEL_ID,
                "tool_trace": [
                    {
                        "order": 1,
                        "tool": "math_router",
                        "used": True,
                        "result_count": 1,
                        "decision": route_info.get("use_math_tool"),
                        "reason": route_info.get("reason"),
                    },
                    {
                        "order": 2,
                        "tool": "math_tool_orchestrator",
                        "used": True,
                        "tool_called": tool_called,
                        "result_count": len(tool_events),
                        "duration_ms": math_result.get("duration_ms"),
                    },
                ],
                "retrieved_chunks": [],
                "dp_db_results": [],
                "web_sources": [],
                "math_tool_trace": tool_events,
                "duration_ms": math_result.get("duration_ms"),
            }
        except Exception as exc:
            last_error = exc
            logger.warning(
                "orchestrator_math_tool_model_failed model=%s error=%s",
                model_name,
                exc,
            )
            try:
                math_result = run_math_tool_via_json_plan(
                    client=client,
                    model=model_name,
                    question=question,
                )
                tool_called = bool(math_result.get("tool_called"))
                tool_events = math_result.get("tool_events", [])
                answer = (math_result.get("final_answer") or "").strip()
                if not answer and tool_called and tool_events:
                    last_tool_result = tool_events[-1].get("tool_result", {})
                    if last_tool_result.get("ok"):
                        answer = str(last_tool_result.get("formatted_result") or last_tool_result.get("result") or "").strip()

                if answer:
                    return {
                        "question": question,
                        "answer": answer,
                        "sources_used": ["math_tool"] if tool_called else [],
                        "vector_queried_first": False,
                        "model_used": PUBLIC_MODEL_ID,
                        "tool_trace": [
                            {
                                "order": 1,
                                "tool": "math_router",
                                "used": True,
                                "result_count": 1,
                                "decision": route_info.get("use_math_tool"),
                                "reason": route_info.get("reason"),
                            },
                            {
                                "order": 2,
                                "tool": "math_tool_json_fallback",
                                "used": True,
                                "tool_called": tool_called,
                                "result_count": len(tool_events),
                                "duration_ms": math_result.get("duration_ms"),
                                "fallback_after_error": str(exc),
                            },
                        ],
                        "retrieved_chunks": [],
                        "dp_db_results": [],
                        "web_sources": [],
                        "math_tool_trace": tool_events,
                        "duration_ms": math_result.get("duration_ms"),
                    }
            except Exception as fallback_exc:
                logger.warning(
                    "orchestrator_math_tool_json_fallback_failed model=%s error=%s",
                    model_name,
                    fallback_exc,
                )

    direct_result = _direct_math_tool_result(question)
    if direct_result:
        return {
            "question": question,
            "answer": direct_result["answer"],
            "sources_used": ["math_tool"],
            "vector_queried_first": False,
            "model_used": PUBLIC_MODEL_ID,
            "tool_trace": [
                {
                    "order": 1,
                    "tool": "math_router",
                    "used": True,
                    "result_count": 1,
                    "decision": route_info.get("use_math_tool"),
                    "reason": route_info.get("reason"),
                },
                {
                    "order": 2,
                    "tool": "python_math_tool",
                    "used": True,
                    "tool_called": True,
                    "result_count": 1,
                    "fallback": "direct_after_model_error",
                    "error": str(last_error) if last_error else None,
                },
            ],
            "retrieved_chunks": [],
            "dp_db_results": [],
            "web_sources": [],
            "math_tool_trace": [direct_result["tool_event"]],
            "duration_ms": None,
        }

    return {
        "question": question,
        "answer": f"Temporary math tool error: {last_error}",
        "sources_used": [],
        "vector_queried_first": False,
        "model_used": PUBLIC_MODEL_ID,
        "tool_trace": [
            {
                "order": 1,
                "tool": "math_router",
                "used": True,
                "result_count": 1,
                "decision": route_info.get("use_math_tool"),
                "reason": route_info.get("reason"),
            },
            {
                "order": 2,
                "tool": "math_tool_orchestrator",
                "used": True,
                "tool_called": False,
                "result_count": 0,
                "error": str(last_error) if last_error else "unknown error",
            },
        ],
        "retrieved_chunks": [],
        "dp_db_results": [],
        "web_sources": [],
        "math_tool_trace": [],
        "duration_ms": None,
    }


def _is_public_current_package_query(question: str) -> bool:
    q = (question or "").lower()
    asks_current = any(token in q for token in ("latest", "current", "recent", "release", "version", "published"))
    asks_package = bool(_extract_known_package_name(question)) or any(token in q for token in PACKAGE_HINTS)
    asks_internal = any(
        token in q
        for token in (
            "audit",
            "metadata",
            "processing failure",
            "validation",
            "cross-reference",
            "cross reference",
            "internal",
            "job",
            "jobs",
            "status",
            "quarantine",
            "owner",
        )
    )
    return asks_current and asks_package and not asks_internal


def _is_public_general_knowledge_query(question: str) -> bool:
    q = (question or "").lower()
    if not q:
        return False

    if detect_internal_data_domains(question):
        return False

    normalized_q = (
        q.replace("ç", "c")
        .replace("ğ", "g")
        .replace("ı", "i")
        .replace("ö", "o")
        .replace("ş", "s")
        .replace("ü", "u")
    )

    public_topic_markers = (
        "world cup",
        "dunya kupasi",
        "fifa",
        "olympics",
        "olympic",
        "nufus",
        "population",
        "baskent",
        "capital",
        "ulkeler",
        "ilce",
        "sehir",
        "district",
        "province",
        "country",
        "countries",
    )
    if any(marker in normalized_q for marker in public_topic_markers):
        return True

    if re.search(r"n\w?fus", normalized_q):
        return True

    if "ilce" in normalized_q and any(token in normalized_q for token in ("kac", "nedir", "nedir?", "kimdir")):
        return True

    if any(token in normalized_q for token in ("ulke", "ulkeler", "country", "countries")) and any(
        ask in normalized_q for ask in ("hangi", "which", "where", "nerede", "oynanacak", "host")
    ):
        return True

    has_year = bool(re.search(r"\b(?:19|20)\d{2}\b", normalized_q))
    event_markers = ("cup", "kupa", "fifa", "olympic", "euro", "tournament", "turnuva")
    return has_year and any(marker in normalized_q for marker in event_markers)


def _normalize_public_text(question: str) -> str:
    return (question or "").lower().translate(
        str.maketrans(
            {
                "\u00e7": "c",
                "\u011f": "g",
                "\u0131": "i",
                "\u00f6": "o",
                "\u015f": "s",
                "\u00fc": "u",
            }
        )
    )


def _looks_like_public_civic_query(question: str) -> bool:
    normalized_q = _normalize_public_text(question)
    if not normalized_q or detect_internal_data_domains(question):
        return False

    if "ilce" in normalized_q and any(token in normalized_q for token in ("kac", "nedir", "kimdir", "nufus", "population")):
        return True

    if re.search(r"il.?e", normalized_q) and (
        re.search(r"ka.?t", normalized_q)
        or re.search(r"n.?fus", normalized_q)
        or "population" in normalized_q
    ):
        return True

    if re.search(r"n\w?fus", normalized_q):
        return True

    if any(token in normalized_q for token in ("ulke", "ulkeler", "country", "countries")) and any(
        ask in normalized_q for ask in ("hangi", "which", "where", "nerede", "oynanacak", "host")
    ):
        return True

    return False


def _is_internal_dp_db_candidate(question: str) -> bool:
    q = (question or "").lower()
    domains = detect_internal_data_domains(question)
    if not domains:
        return False

    if "product" in domains:
        return True

    if "aggregation" in domains or "validation" in domains:
        return True

    if "formula" in domains and not _is_general_math_formula_query(question):
        formula_internal_hints = (
            "how many",
            "count",
            "latest",
            "saved",
            "created",
            "snapshot",
            "chart",
            "datapoint",
            "variable",
            "bulk",
            "stored",
            "db",
            "database",
            "rule",
            "formula",
        )
        return any(token in q for token in formula_internal_hints)

    return False


def _should_skip_math_router(question: str) -> bool:
    domains = detect_internal_data_domains(question)
    if not domains:
        return False

    if "product" in domains:
        return True

    if "aggregation" in domains or "validation" in domains:
        return True

    if "formula" in domains and not _is_general_math_formula_query(question):
        return True

    return False


def _trim_conversation_context(conversation_context: str | None, max_chars: int = 1200) -> str:
    value = (conversation_context or "").strip()
    if len(value) <= max_chars:
        return value
    return value[-max_chars:]


def _question_needs_conversation_context(question: str) -> bool:
    q = (question or "").strip().lower()
    if not q:
        return False

    followup_starts = ("and ", "what about", "how about", "peki", "ya peki", "then ")
    referential_terms = (
        " it ",
        " its ",
        " this ",
        " that ",
        " same package",
        "same version",
        "bunun",
        "buna",
        "bunu",
        "onun",
        "onu",
        "aynı",
        "ayni",
    )

    if any(q.startswith(prefix) for prefix in followup_starts):
        return True

    if any(term in f" {q} " for term in referential_terms):
        return True

    return len(q.split()) <= 8 and any(token in q for token in ("latest", "version", "cve", "advisory", "security"))


def _extract_recent_reference_text(conversation_context: str | None) -> str:
    lines = [line.strip() for line in (conversation_context or "").splitlines() if line.strip()]
    if not lines:
        return ""

    for line in reversed(lines):
        if line.startswith("USER:") or line.startswith("ASSISTANT:"):
            value = line.split(":", 1)[-1].strip()
            value = re.sub(r"^(tell me about|what do you know about|explain|describe)\s+", "", value, flags=re.IGNORECASE)
            return value.strip()

    return lines[-1]


def _looks_turkish(text: str) -> bool:
    lowered = (text or "").lower()
    return any(ch in lowered for ch in "çğıöşü") or any(
        token in lowered
        for token in ("kaç", "kim", "hangi", "bunun", "onun", "sürüm", "yaş", "paket", "mı", "mi", "mu", "mü")
    )


def _extract_recent_named_entity(conversation_context: str | None) -> str | None:
    lines = [line.strip() for line in (conversation_context or "").splitlines() if line.strip()]
    if not lines:
        return None

    name_pattern = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,1}\b")

    user_lines = [line for line in lines if line.startswith("USER:")]
    other_lines = [line for line in lines if not line.startswith("USER:")]

    for line_group in (reversed(user_lines), reversed(other_lines)):
        for line in line_group:
            matches = name_pattern.findall(line)
            if matches:
                return matches[-1].strip()

    return None


def _build_conversation_state(conversation_context: str | None = None) -> dict[str, str]:
    history = _trim_conversation_context(conversation_context)
    return {
        "active_package": _extract_known_package_name(history or "") or "",
        "active_entity": _extract_recent_named_entity(history) or "",
        "history": history,
    }


def _question_intent(question: str) -> str:
    q = (question or "").lower()
    if any(token in q for token in ("latest", "version", "sürüm", "surum")):
        return "version"
    if any(token in q for token in ("security", "advisory", "vulnerability", "cve", "güvenlik", "guvenlik")):
        return "security"
    if any(token in q for token in ("how old", "kaç yaş", "kaç yaşında", "age", "yaş")):
        return "age"
    if any(token in q for token in ("which team", "hangi takım", "hangi takim", "plays for", "oynuyor")):
        return "team"
    return "generic"


def _build_state_based_followup_rewrite(question: str, conversation_context: str | None = None) -> str:
    base_question = (question or "").strip()
    state = _build_conversation_state(conversation_context)
    intent = _question_intent(base_question)
    turkish = _looks_turkish(base_question)

    active_package = state.get("active_package") or ""
    active_entity = state.get("active_entity") or ""

    if active_package:
        if intent == "version":
            return f"{active_package} npm paketinin son sürümü ne?" if turkish else f"What is the latest version of {active_package} on npm?"
        if intent == "security":
            return f"{active_package} için public security advisory var mı?" if turkish else f"Does {active_package} have any public security advisory?"

    if active_entity:
        if intent == "age":
            return f"{active_entity} kaç yaşında?" if turkish else f"How old is {active_entity}?"
        if intent == "team":
            return f"{active_entity} hangi takımda oynuyor?" if turkish else f"Which team does {active_entity} play for?"

    return base_question


def _rewritten_question_looks_valid(
    original_question: str,
    rewritten_question: str,
    conversation_context: str | None = None,
) -> bool:
    original = (original_question or "").strip()
    rewritten = (rewritten_question or "").strip()
    if not original or not rewritten:
        return False

    intent = _question_intent(original)
    lowered = rewritten.lower()
    state = _build_conversation_state(conversation_context)

    if intent == "version" and not any(token in lowered for token in ("version", "sürüm", "surum")):
        return False
    if intent == "security" and not any(token in lowered for token in ("security", "advisory", "vulnerability", "cve", "güvenlik", "guvenlik")):
        return False
    if intent == "age" and not any(token in lowered for token in ("how old", "kaç yaş", "kaç yaşında", "age", "yaş")):
        return False
    if intent == "team" and not any(token in lowered for token in ("team", "takım", "takim", "plays for", "oynuyor")):
        return False

    active_package = state.get("active_package") or ""
    if active_package and intent in {"version", "security"} and active_package.lower() not in lowered:
        return False

    active_entity = state.get("active_entity") or ""
    if active_entity and intent in {"age", "team"} and active_entity.lower() not in lowered:
        return False

    return True


def _sanitize_rewritten_question(candidate: str, original_question: str) -> str:
    value = (candidate or "").strip()
    if not value:
        return original_question

    value = re.sub(r"(?im)^rewritten question\s*:\s*", "", value).strip()
    value = re.sub(r"(?im)^standalone question\s*:\s*", "", value).strip()

    if "\n" in value:
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        if lines:
            value = lines[-1]

    value = value.strip().strip("\"'`")
    if not value:
        return original_question

    return value


def _rewrite_followup_question_with_model(
    question: str,
    conversation_context: str | None = None,
) -> str | None:
    history = _trim_conversation_context(conversation_context)
    if not history or not _question_needs_conversation_context(question):
        return None

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Rewrite the user's latest question into a standalone question using the conversation reference.\n"
                "Keep the original language.\n"
                "Preserve the user's intent exactly.\n"
                "If the question is already standalone, return it unchanged.\n"
                "Return only the rewritten question.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Conversation reference:\n{history}\n\n"
                f"Current question:\n{question}"
            ),
        },
    ]

    last_error: Exception | None = None
    for model in _build_model_candidates():
        try:
            response = create_chat_completion(
                model=model,
                messages=cast(Any, messages),
                temperature=0.0,
            )
            raw = response.choices[0].message.content or ""
            rewritten = _sanitize_rewritten_question(raw, question)
            if rewritten and _rewritten_question_looks_valid(question, rewritten, conversation_context):
                return rewritten
        except Exception as exc:
            last_error = exc
            logger.warning(
                "conversation_rewrite_model_failed model=%s error=%s",
                model,
                exc,
            )

    if last_error:
        logger.info("conversation_rewrite_fallback error=%s", last_error)
    return None


def _heuristic_followup_rewrite(question: str, conversation_context: str | None = None) -> str:
    base_question = (question or "").strip()
    history = _trim_conversation_context(conversation_context)
    if not base_question or not history:
        return base_question
    if not _question_needs_conversation_context(base_question):
        return base_question
    recent_reference = _extract_recent_reference_text(history)
    if not recent_reference:
        return base_question
    return f"{recent_reference} {base_question}".strip()


def _build_effective_question(question: str, conversation_context: str | None = None) -> str:
    base_question = (question or "").strip()
    if not base_question:
        return base_question

    state_based = _build_state_based_followup_rewrite(base_question, conversation_context)
    if state_based and state_based.strip() != base_question.strip():
        return state_based

    rewritten = _rewrite_followup_question_with_model(base_question, conversation_context)
    if rewritten:
        return rewritten

    return _heuristic_followup_rewrite(base_question, conversation_context)


def _build_conversation_reference_block(conversation_context: str | None = None) -> str:
    history = _trim_conversation_context(conversation_context)
    if not history:
        return ""
    return (
        "CONVERSATION REFERENCE:\n"
        "Use this only to resolve what the user is referring to. "
        "Do not treat it as factual evidence unless the retrieval context also supports it.\n"
        f"{history}"
    )


def _normalize_source_for_chat(source: str | None) -> str | None:
    value = (source or "").strip().lower()
    if not value:
        return None

    if value == ROUTING_GUIDANCE_SOURCE:
        logger.info(
            "ignoring_guidance_source_filter source=%s reason=routing_seed_should_not_constrain_user_questions",
            source,
        )
        return None

    return source

def _has_strong_vector_match(vector_matches: list[dict[str, Any]], threshold: float = 0.32) -> bool:
    for match in vector_matches:
        try:
            similarity = float(match.get("similarity", 0.0))
        except Exception:
            similarity = 0.0
        if similarity >= threshold:
            return True
    return False


def _top_vector_similarity(vector_matches: list[dict[str, Any]]) -> float:
    top = 0.0
    for match in vector_matches:
        try:
            similarity = float(match.get("similarity", 0.0))
        except Exception:
            similarity = 0.0
        top = max(top, similarity)
    return top


def _routing_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", (text or "").lower())
        if len(token) >= 3
    }

def _looks_like_orchestration_guidance_chunk(content: str) -> bool:
    text = (content or "").lower()
    guidance_signals = (
        "vector db first",
        "first source of truth",
        "orchestration decisions",
        "orchestration guidance",
        "tools were used",
        "responses must show which sources",
        "query the vector db first",
        "assistant should use vector db first",
        "module boundaries",
        "web search answers",
    )
    return any(signal in text for signal in guidance_signals)


def _guidance_only_vector_matches(
    question: str,
    vector_matches: list[dict[str, Any]],
    limit: int = 3,
) -> bool:
    top_matches = vector_matches[:limit]
    if not top_matches:
        return False

    question_tokens = _routing_tokens(question)
    non_guidance_match_count = 0

    for match in top_matches:
        content = str(match.get("content") or "")
        if not _looks_like_orchestration_guidance_chunk(content):
            non_guidance_match_count += 1
            continue

        content_tokens = _routing_tokens(content)
        overlap = len(question_tokens & content_tokens)
        if overlap >= 3:
            non_guidance_match_count += 1

    return non_guidance_match_count == 0


def _best_vector_question_overlap(
    question: str,
    vector_matches: list[dict[str, Any]],
    limit: int = 3,
) -> int:
    question_tokens = _routing_tokens(question)
    best_overlap = 0

    for match in vector_matches[:limit]:
        content_tokens = _routing_tokens(str(match.get("content") or ""))
        overlap = len(question_tokens & content_tokens)
        best_overlap = max(best_overlap, overlap)

    return best_overlap


def _vector_evidence_is_sufficient(
    question: str,
    vector_matches: list[dict[str, Any]],
    source: str | None = None,
) -> bool:
    if not vector_matches:
        return False

    if source:
        return True

    if _guidance_only_vector_matches(question, vector_matches):
        return False

    top_similarity = _top_vector_similarity(vector_matches)
    best_overlap = _best_vector_question_overlap(question, vector_matches)

    if top_similarity < ROUTING_MIN_VECTOR_THRESHOLD:
        return False

    if best_overlap <= 1:
        return False

    if top_similarity < ROUTING_STRONG_VECTOR_THRESHOLD and best_overlap <= 2:
        return False

    return True


def _build_vector_routing_digest(
    vector_matches: list[dict[str, Any]],
    limit: int = 3,
    snippet_chars: int = 220,
) -> str:
    if not vector_matches:
        return "No vector matches."

    lines = []
    for index, match in enumerate(vector_matches[:limit], start=1):
        try:
            similarity = float(match.get("similarity", 0.0))
        except Exception:
            similarity = 0.0
        source = str(match.get("source") or "").strip() or "unknown"
        content = re.sub(r"\s+", " ", str(match.get("content") or "")).strip()
        content = content[:snippet_chars]
        lines.append(
            f"{index}. similarity={similarity:.3f} | source={source} | snippet={content}"
        )
    return "\n".join(lines)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    value = (text or "").strip()
    if not value:
        return None

    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    match = re.search(r"\{.*\}", value, flags=re.DOTALL)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return None

    return parsed if isinstance(parsed, dict) else None


def _fallback_route_decision(
    question: str,
    vector_matches: list[dict[str, Any]],
    source: str | None = None,
) -> dict[str, Any]:
    top_similarity = _top_vector_similarity(vector_matches)
    guidance_only = _guidance_only_vector_matches(question, vector_matches)
    evidence_sufficient = _vector_evidence_is_sufficient(question, vector_matches, source=source)

    if (guidance_only or not evidence_sufficient) and not source:
        return {
            "route": "web",
            "confidence": 0.78,
            "reason": "Top vector matches are not sufficient evidence for an internal answer, so route to web.",
            "top_similarity": round(top_similarity, 3),
        }

    if source and top_similarity >= ROUTING_MIN_VECTOR_THRESHOLD:
        return {
            "route": "vector_only",
            "confidence": 0.70,
            "reason": "LLM router was unavailable; source-filtered vector evidence was sufficient, so falling back to vector_only.",
            "top_similarity": round(top_similarity, 3),
        }

    if top_similarity >= ROUTING_STRONG_VECTOR_THRESHOLD:
        return {
            "route": "vector_only",
            "confidence": 0.62,
            "reason": "LLM router was unavailable; strong vector evidence suggests an internal answer, so falling back to vector_only.",
            "top_similarity": round(top_similarity, 3),
        }

    return {
        "route": "web",
        "confidence": 0.60,
        "reason": "Vector retrieval is weak, so the question is treated as external/public and routed to web search.",
        "top_similarity": round(top_similarity, 3),
    }


def _route_question_with_llm(
    question: str,
    vector_matches: list[dict[str, Any]],
    conversation_context: str | None = None,
    source: str | None = None,
) -> dict[str, Any]:
    history = _trim_conversation_context(conversation_context)
    top_similarity = _top_vector_similarity(vector_matches)
    vector_digest = _build_vector_routing_digest(vector_matches)
    guidance_only = _guidance_only_vector_matches(question, vector_matches)
    evidence_sufficient = _vector_evidence_is_sufficient(question, vector_matches, source=source)

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are a routing classifier for a RAG application.\n"
                "Decide how to answer the user's question.\n"
                "Available routes:\n"
                "- vector_only: the question is about the app, ingested documents, or internal architecture/explanations answerable from vector context.\n"
                "- vector_and_dp_db: the question is about internal structured facts that usually require record lookup in the Data Processing DB, such as runs, jobs, statuses, audit/history, counts, failures, ownership, or metadata.\n"
                "- web: the question is primarily about public, external, current, or general-world information and should be answered with web search.\n"
                "Use the question semantics first, then use vector similarity as supporting evidence.\n"
                "Low or weak vector similarity is evidence that the question may be external.\n"
                "If vector matches only describe retrieval rules, tool usage, orchestration, or system policy, they are not evidence that the answer is internal.\n"
                "When the top vector snippets are guidance-only rather than factual evidence for the asked subject, choose web.\n"
                "If the retrieved snippets do not materially overlap with the user question's subject, choose web.\n"
                "Choose vector_and_dp_db only when the user is asking for specific internal operational facts that are unlikely to be fully answered by document snippets alone.\n"
                "Do not rely on fixed keyword matching. Infer intent from meaning.\n"
                "Return strict JSON only with keys: route, confidence, reason.\n"
                "route must be one of: vector_only, vector_and_dp_db, web.\n"
                "confidence must be a number between 0 and 1.\n"
                "reason must be a short sentence.\n"
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"Conversation reference:\n{history or 'None'}\n\n"
                f"Source filter provided: {'yes' if source else 'no'}\n"
                f"Top vector similarity: {top_similarity:.3f}\n\n"
                f"Top matches guidance-only: {'yes' if guidance_only else 'no'}\n\n"
                f"Vector evidence sufficient for internal answer: {'yes' if evidence_sufficient else 'no'}\n\n"
                f"Top vector matches:\n{vector_digest}"
            ),
        },
    ]

    last_error: Exception | None = None
    used_model = ""

    for model in _build_model_candidates():
        used_model = model
        try:
            response = create_chat_completion(
                model=model,
                messages=cast(Any, messages),
                temperature=0.0,
            )
            raw = response.choices[0].message.content or ""
            parsed = _extract_json_object(raw)
            if not parsed:
                continue

            route = str(parsed.get("route") or "").strip()
            if route not in {"vector_only", "vector_and_dp_db", "web"}:
                continue

            try:
                confidence = float(parsed.get("confidence", 0.0))
            except Exception:
                confidence = 0.0

            confidence = max(0.0, min(confidence, 1.0))
            reason = str(parsed.get("reason") or "").strip() or "No reason provided."

            if (guidance_only or not evidence_sufficient) and route != "web" and not source:
                return {
                    "route": "web",
                    "confidence": max(confidence, 0.78),
                    "reason": "Vector evidence is not sufficient for an internal answer, so the question should be answered via web search.",
                    "top_similarity": round(top_similarity, 3),
                    "model_used": used_model,
                }

            return {
                "route": route,
                "confidence": confidence,
                "reason": reason,
                "top_similarity": round(top_similarity, 3),
                "model_used": used_model,
            }
        except Exception as exc:
            last_error = exc
            logger.warning(
                "routing_model_failed model=%s error=%s",
                model,
                exc,
            )

    if last_error:
        logger.info("routing_model_fallback error=%s", last_error)

    fallback = _fallback_route_decision(question, vector_matches, source=source)
    fallback["model_used"] = "routing_fallback"
    return fallback


def _build_vector_source_names(matches: list[dict[str, Any]]) -> list[str]:
    names = []

    for match in matches:
        src = str(match.get("source") or "").strip()
        if src and src not in names:
            names.append(f"Vector DB: {src}")

    return names or ["Vector DB"]


def _build_web_source_names(web_results: list[dict[str, Any]]) -> list[str]:
    names = []

    for result in web_results[:5]:
        title = str(result.get("title") or "").strip()
        url = str(result.get("url") or "").strip()
        domain = str(result.get("source") or "").strip()

        if url:
            label = domain or title or "web source"
            item = f"[Web: {label}]({url})"
        else:
            item = f"Web: {domain or title}"

        if item not in names:
            names.append(item)

    return names


def _has_relevant_vector_match(
    vector_matches: list[dict[str, Any]],
    min_similarity: float = 0.22,
) -> bool:
    for match in vector_matches:
        try:
            similarity = float(match.get("similarity", 0.0))
        except Exception:
            similarity = 0.0

        if similarity >= min_similarity and str(match.get("content") or "").strip():
            return True

    return False


def _query_vector_first(
    question: str,
    top_k: int,
    source: str | None,
) -> dict[str, Any]:
    start = perf_counter()

    if count_documents() == 0:
        return {
            "ok": False,
            "matches": [],
            "context": "",
            "error": "Vector database is empty.",
            "duration_ms": round((perf_counter() - start) * 1000, 1),
        }

    retrieved = retrieve_context(
        question=question,
        top_k=top_k,
        source=source,
    )

    return {
        "ok": True,
        "matches": retrieved.get("matches", []),
        "context": retrieved.get("context", ""),
        "error": None,
        "duration_ms": round((perf_counter() - start) * 1000, 1),
    }


def _chat_history_messages(
    history: list[dict[str, Any]] | None,
    max_messages: int = 500,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for item in (history or [])[-max_messages:]:
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in {"user", "assistant"} or not content:
            continue
        messages.append({"role": role, "content": content})
    return messages


def _chat_history_text(
    history: list[dict[str, Any]] | None,
    max_messages: int = 500,
) -> str:
    lines = []
    for message in _chat_history_messages(history, max_messages=max_messages):
        role = "Kullanıcı" if message["role"] == "user" else "Asistan"
        lines.append(f"{role}: {message['content']}")
    return "\n".join(lines)


def _answer_from_chat_memory(
    question: str,
    history: list[dict[str, Any]] | None,
) -> str | None:
    q = (question or "").lower().strip()
    asks_name = any(
        pattern in q
        for pattern in (
            "adım ne",
            "adim ne",
            "adım neydi",
            "adim neydi",
            "ismim ne",
            "ismim neydi",
            "benim adım ne",
            "benim adim ne",
            "benim adım neydi",
            "benim adim neydi",
            "bana ne deniyor",
        )
    )
    if not asks_name:
        return None

    for item in reversed(history or []):
        if str(item.get("role") or "").lower() != "user":
            continue
        content = str(item.get("content") or "").strip()
        name = _extract_name_from_user_message(content)
        if name:
            return f"Senin adın {name}."

    return None


def _extract_name_from_user_message(message: str) -> str | None:
    text = " ".join((message or "").strip().split())
    if not text:
        return None

    lowered = text.lower()
    if any(
        phrase in lowered
        for phrase in (
            "adım ne",
            "adim ne",
            "adım neydi",
            "adim neydi",
            "ismim ne",
            "ismim neydi",
            "benim adım ne",
            "benim adim ne",
            "benim adım neydi",
            "benim adim neydi",
            "adımı biliyor",
            "adimi biliyor",
        )
    ):
        return None

    name_word = r"([A-Za-zÇĞİÖŞÜçğıöşü]{2,}(?:\s+[A-Za-zÇĞİÖŞÜçğıöşü]{2,})?)"
    name_patterns = (
        rf"\b(?:benim\s+)?ad[ıi]m\s+{name_word}\b",
        rf"\b(?:benim\s+)?adim\s+{name_word}\b",
        rf"\bismim\s+{name_word}\b",
        rf"\b(?:merhaba|selam|hey|hi)?\s*ben\s+{name_word}\b",
        rf"\b(?:merhaba|selam|hey|hi)?\s*{name_word}\s+ben\b",
        rf"\bbana\s+{name_word}\s+de\b",
    )
    rejected_names = {
        "ne",
        "neydi",
        "nedir",
        "kim",
        "ney",
        "bilmiyorum",
        "söylemedim",
        "soylemedim",
        "nasılsın",
        "nasilsin",
    }

    for pattern in name_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        name = re.sub(r"\s+", " ", match.group(1)).strip(" .,!?:;")
        name_parts = [part.lower() for part in name.split()]
        if name.lower() in rejected_names or any(part in rejected_names for part in name_parts):
            continue
        return " ".join(part[:1].upper() + part[1:] for part in name.split())

    return None


def _should_answer_directly(question: str) -> bool:
    q = (question or "").lower().strip()
    if not q:
        return False

    if detect_internal_data_domains(question):
        return False

    if _is_public_general_knowledge_query(question):
        return False

    if _looks_like_public_civic_query(question):
        return False

    if _is_math_tool_candidate(question):
        return False

    tool_markers = (
        "pdf",
        "document",
        "source",
        "vector",
        "dp db",
        "database",
        "audit",
        "metadata",
        "validation",
        "package",
        "npm",
        "cve",
        "github",
        "latest",
        "current",
        "web",
        "internet",
        "internette",
        "ara",
        "search",
        "water main",
        "crli",
        "ili",
    )
    if any(marker in q for marker in tool_markers):
        return False

    casual_markers = (
        "hi",
        "hello",
        "hey",
        "naber",
        "selam",
        "merhaba",
        "nasılsın",
        "nasilsin",
        "en sevdiğin",
        "en sevdigin",
        "what is your favorite",
        "who are you",
        "kimsin",
    )
    if any(marker in q for marker in casual_markers):
        return True

    return len(q.split()) <= 12


def _call_direct_llm(
    question: str,
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    history_text = _chat_history_text(history)
    user_content = question
    if history_text:
        user_content = (
            "Sohbet geçmişi:\n"
            f"{history_text}\n\n"
            "Son kullanıcı mesajı:\n"
            f"{question}\n\n"
            "Görev: Son mesaja cevap ver. Son mesaj önceki konuşmaya gönderme yapıyorsa cevabı sohbet geçmişinden çıkar. "
            "Kullanıcının daha önce söylediği ad, tercih, konu, karar ve ayrıntıları hatırla. "
            "Bilgi sohbet geçmişinde varsa 'söylemediniz' deme."
        )

    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "Sen ciddi ve profesyonel bir Türkçe asistansın.\n"
                "Son kullanıcı mesajını yanıtla.\n"
                "Sohbet geçmişi verilmişse, önceki mesajlardaki ad, tercih, konu ve göndermeleri dikkate al.\n"
                "Geçmişte açıkça verilen bilgiyi bilmiyormuş gibi davranma.\n"
                "Araç, kaynak veya yedek akış kullandığını söyleme.\n"
                "Kısa ve doğal cevap ver."
            ),
        },
        {"role": "user", "content": user_content},
    ]

    last_error = None
    used_model = ""

    for model in _build_model_candidates():
        used_model = model
        try:
            response = create_chat_completion(
                model=model,
                messages=cast(Any, messages),
                temperature=0.7,
            )
            return (response.choices[0].message.content or "").strip(), used_model
        except Exception as exc:
            last_error = exc
            logger.warning(
                "orchestrator_direct_llm_failed model=%s error=%s",
                model,
                exc,
            )

    return f"Temporary model error: {last_error}", used_model


def _call_llm(
    question: str,
    context: str,
    source_names: list[str],
    history: list[dict[str, Any]] | None = None,
) -> tuple[str, str]:
    history_text = _chat_history_text(history)
    history_block = f"\n\nPrevious chat:\n{history_text}" if history_text else ""
    style_instructions = _answer_style_instructions(question)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are the Data Processing App chat assistant.\n"
                "Use only the provided context.\n"
                "The vector database is always the first source of truth.\n"
                "If DP DB context exists, use it for structured/internal facts.\n"
                "If DP DB context contains an exact count, status, timestamp, snapshot, or mapped row value, treat that as the authoritative internal fact.\n"
                "Do not weaken a precise DP DB result just because Vector DB context is generic guidance.\n"
                "If web context exists, use it only for external or current facts.\n"
                "Only mention tools listed under TOOLS_USED.\n"
                "Do not claim DP DB or web search was used unless it appears in TOOLS_USED.\n"
                "Do not narrate your retrieval process, planning, or which tool should run next.\n"
                "The tools have already run; answer directly from the evidence.\n"
                "Do not say things like 'we should query', 'we will now use', or 'vector db is queried first'.\n"
                "Do not invent missing facts.\n"
                "Keep the answer concise.\n"
                "Mention which tools/sources were used."
                "Do not print the TOOLS_USED block verbatim.\n"
                "Do not invent versions, CVEs, advisories, dates, or release notes.\n"
                "If a version or CVE is not explicitly present in the context, say it was not verified from the provided sources.\n"
                "Use concise wording; do not say 'Queryed'.\n"
                "If web_search appears in TOOLS_USED, use the WEB SEARCH CONTEXT directly instead of talking about the search process.\n"
                "Never say web search was not queried when web_search appears in TOOLS_USED.\n"
                "If data_processing_db appears in TOOLS_USED, use the DP DB context only when it contributes factual evidence.\n"
                "Write the final answer as a comparison when the question asks to compare.\n"
                "Preserve vulnerability ranges exactly as written in WEB SEARCH CONTEXT.\n"
                "Do not say a version is secure, fixed, or not affected unless the context explicitly says so.\n"
                "Prefer exact dates over relative phrases like '8 years ago' when the context provides them.\n"
                "If an exact date is not present in the context, say it was not verified.\n"
                "Do not merge similarly named packages unless the context explicitly says they are the same package.\n"
                "Only state a package version, advisory, vulnerability, or published date if it is explicitly present in the provided context.\n"
                "If multiple similarly named packages appear, answer only for the exact package asked by the user unless the question explicitly asks for comparison.\n"
                "Do not broaden the answer to related packages or scoped packages.\n"
                "Prefer exact published dates when present in the context instead of relative phrases like '8 years ago' or 'a month ago'.\n"
                "If the exact published date is not present in the context, say the exact date was not verified.\n"
                "For web results, do not infer that a newer version fixes a vulnerability unless the context explicitly says so.\n"
                "Do not mention Data Processing DB when data_processing_db is not in TOOLS_USED.\n"
                "Do not use relative publish times like '8 years ago' unless no exact date is present in the context.\n"
                "If a CONVERSATION REFERENCE block exists, use it only to resolve what the user is referring to.\n"
                + style_instructions
            ),
        },
        {
            "role": "user",
            "content": f"Question:\n{question}{history_block}\n\nContext:\n{context}",
        },
    ]

    last_error = None
    used_model = ""

    for model in _build_model_candidates():
        used_model = model
        try:
            response = create_chat_completion(
                model=model,
                messages=cast(Any, messages),
                temperature=0.0,
            )
            raw_answer = response.choices[0].message.content or ""
            return clean_answer(raw_answer, source_names), used_model
        except Exception as exc:
            last_error = exc
            logger.warning(
                "orchestrator_llm_model_failed model=%s error=%s",
                model,
                exc,
            )

    return clean_answer(
        f"Temporary model error: {last_error}",
        source_names,
    ), used_model

def _build_web_query(question: str) -> str:
    original = (question or "").strip()
    q = original.lower()
    security_lookup = any(token in q for token in ("security", "advisory", "vulnerability", "cve"))
    version_lookup = any(token in q for token in ("latest", "version", "npm"))
    package_name = _extract_known_package_name(question)

    if package_name:
        if security_lookup:
            return f"{package_name} npm security advisory vulnerability cve"
        if version_lookup:
            return f"{package_name} npm latest version"
        return f"{package_name} npm package"

    cleaned = re.sub(
        r"\b(search (on )?web|search the web|use web|from web|on the web|web search|search online)\b",
        "",
        original,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(
        r"\b(internette ara|webde ara|webden bul)\b",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ?")
    return cleaned or original



def _extract_npm_package_from_url(url: str) -> str | None:
    match = re.search(
        r"npmjs\.com/package/([^/?#]+(?:/[^/?#]+)?)",
        url or "",
        re.IGNORECASE,
    )
    if not match:
        return None
    return match.group(1).strip().lower()


def _extract_semver_candidates(text: str) -> list[str]:
    return re.findall(r"\b\d+\.\d+\.\d+\b", text or "")


def _build_deterministic_package_web_answer(
    question: str,
    web_results: list[dict[str, Any]],
    source_names: list[str],
) -> str | None:
    q = (question or "").lower()
    package_name = _extract_known_package_name(question)
    if not package_name:
        return None

    if not any(token in q for token in ("latest", "version", "npm")):
        return None

    for result in web_results:
        domain = str(result.get("source") or "").lower().strip()
        url = str(result.get("url") or "")
        if "npmjs.com" not in domain:
            continue

        npm_package_in_url = _extract_npm_package_from_url(url)
        if npm_package_in_url and npm_package_in_url != package_name:
            continue

        blob = " ".join(
            [
                str(result.get("title") or ""),
                str(result.get("content") or ""),
                url,
            ]
        )
        versions = _extract_semver_candidates(blob)
        if not versions:
            continue

        return clean_answer(f"The latest version of {package_name} on npm is {versions[0]}.", source_names)

    return None


def _build_deterministic_dp_db_answer(
    question: str,
    dp_result: dict[str, Any],
    source_names: list[str],
) -> str | None:
    rows = dp_result.get("rows", [])
    if not rows:
        return None

    prefers_turkish = _question_prefers_turkish(question)
    include_ids = _question_requests_ids(question)
    include_timestamps = _question_requests_timestamps(question)
    domain = str(dp_result.get("domain") or "").lower()

    if (
        "formula" in domain
        and {"bulk_formula_id", "bulk_formula_name", "group_key", "group_variable_name", "group_datapoint_id"}.issubset(rows[0])
    ):
        grouped: dict[tuple[Any, Any, Any, Any, Any], list[str]] = {}
        for item in rows:
            key = (
                item.get("bulk_formula_id"),
                item.get("bulk_formula_name"),
                item.get("group_key"),
                item.get("group_name"),
                item.get("result_data_id"),
            )
            mapping = f"{item.get('group_variable_name')} -> {item.get('group_datapoint_id')}"
            grouped.setdefault(key, [])
            if mapping not in grouped[key]:
                grouped[key].append(mapping)

        lines = ["Bulk formula eşleştirmeleri:"] if prefers_turkish else ["Bulk formula mappings:"]
        for (bulk_formula_id, bulk_formula_name, group_key, group_name, result_data_id), mappings in grouped.items():
            label = group_name or group_key or "unknown-group"
            prefix = f"- {bulk_formula_name}"
            if include_ids:
                prefix += f" (id={bulk_formula_id})"
            if prefers_turkish:
                detail = f"{prefix}: grup {label}"
                if result_data_id and include_ids:
                    detail += f", result_data_id={result_data_id}"
                detail += f", eşleşmeler: {', '.join(mappings)}"
            else:
                detail = f"{prefix}: group={label}"
                if result_data_id and include_ids:
                    detail += f", result_data_id={result_data_id}"
                detail += f", mappings={', '.join(mappings)}"
            lines.append(detail)
        return clean_answer("\n".join(lines), source_names)

    if "aggregation" in domain and {"rule_name", "value", "time"}.issubset(rows[0]):
        lines = ["Son aggregation sonuçları:"] if prefers_turkish else ["Recent aggregation results:"]
        for item in rows[:10]:
            parts = [f"- {item.get('rule_name')}: value={item.get('value')}"]
            if include_timestamps or not prefers_turkish:
                parts.append(f"time={item.get('time')}")
            if item.get("interval"):
                parts.append(f"interval={item.get('interval')}")
            lines.append(", ".join(parts))
        return clean_answer("\n".join(lines), source_names)

    if (
        "aggregation" in domain
        and {"rule_name", "method", "interval_value", "interval_unit"}.issubset(rows[0])
    ):
        question_text = (question or "").lower()
        if "average" in question_text:
            lines = ["Average method kullanan aggregation rule'lar:"] if prefers_turkish else ["Aggregation rules that use the average method:"]
        else:
            lines = ["Aggregation rule'lar:"] if prefers_turkish else ["Aggregation rules:"]
        for item in rows[:10]:
            detail = f"- {item.get('rule_name')}"
            if prefers_turkish:
                detail += f" ({item.get('interval_value')} {item.get('interval_unit')}, method={item.get('method')})"
            else:
                detail += f" ({item.get('interval_value')} {item.get('interval_unit')}, method={item.get('method')})"
            lines.append(detail)
        return clean_answer("\n".join(lines), source_names)

    if "product" in domain and {"measurement_name", "avg_value", "unit"}.issubset(rows[0]):
        row = rows[0]
        if prefers_turkish:
            answer = f"{row.get('measurement_name')} değerlerinin ortalaması {row.get('avg_value')} {row.get('unit')}."
            if include_ids and row.get("sample_count") is not None:
                answer += f" Örnek sayısı: {row.get('sample_count')}."
        else:
            answer = f"The average {row.get('measurement_name')} value is {row.get('avg_value')} {row.get('unit')}."
            if include_ids and row.get("sample_count") is not None:
                answer += f" Sample count: {row.get('sample_count')}."
        return clean_answer(answer, source_names)

    if "product" in domain and {"asset_label", "measurement_name", "latest_value"}.issubset(rows[0]):
        filtered_rows = rows
        lower_question = (question or "").lower()
        for field in ("district_name", "region_name", "asset_label"):
            matching_rows = [
                item
                for item in rows
                if item.get(field) and str(item.get(field)).lower().split()[0] in lower_question
            ]
            if matching_rows:
                filtered_rows = matching_rows
                break

        selected = filtered_rows[0]
        measurement = selected.get("measurement_name")
        value = selected.get("latest_value")
        unit = selected.get("unit")
        asset_label = selected.get("asset_label")
        if prefers_turkish:
            answer = f"En son {measurement} değeri {asset_label} için {value} {unit}."
            if include_timestamps and selected.get("latest_at"):
                answer += f" Zaman: {selected.get('latest_at')}."
        else:
            answer = f"The latest {measurement} value for {asset_label} is {value} {unit}."
            if include_timestamps and selected.get("latest_at"):
                answer += f" Time: {selected.get('latest_at')}."
        return clean_answer(answer, source_names)

    if len(rows) != 1:
        return None

    row = rows[0]

    if "formula" in domain and "count" in row:
        return clean_answer(
            (
                f"Data Processing DB içinde {row['count']} formula var."
                if prefers_turkish
                else f"There are {row['count']} formulas in the Data Processing DB."
            ),
            source_names,
        )

    if "formula" in domain and "formula_count" in row:
        return clean_answer(
            (
                f"Data Processing DB içinde {row['formula_count']} formula var."
                if prefers_turkish
                else f"There are {row['formula_count']} formulas in the Data Processing DB."
            ),
            source_names,
        )

    if "aggregation" in domain and "aggregation_rule_count" in row:
        return clean_answer(
            (
                f"Data Processing DB içinde {row['aggregation_rule_count']} aggregation rule var."
                if prefers_turkish
                else f"There are {row['aggregation_rule_count']} aggregation rules in the Data Processing DB."
            ),
            source_names,
        )

    if "validation" in domain and "validation_rule_count" in row:
        return clean_answer(
            (
                f"Data Processing DB içinde {row['validation_rule_count']} validation rule var."
                if prefers_turkish
                else f"There are {row['validation_rule_count']} validation rules in the Data Processing DB."
            ),
            source_names,
        )

    if "product" in domain and "asset_count" in row:
        return clean_answer(
            (
                f"Data Processing DB iÃ§inde {row['asset_count']} asset var."
                if prefers_turkish
                else f"There are {row['asset_count']} assets in the Data Processing DB."
            ),
            source_names,
        )

    if "aggregation" in domain and {"rule_id", "rule_name", "started_at", "completed_at", "status"}.issubset(row):
        if prefers_turkish:
            parts = [f"En son çalışan aggregation run {row['rule_name']} için."]
            if row.get("status"):
                parts.append(f"Durum: {row.get('status')}.")
            if include_timestamps:
                parts.append(f"Başlangıç: {row.get('started_at')}.")
                parts.append(f"Bitiş: {row.get('completed_at')}.")
            if include_ids:
                parts.append(f"rule_id={row['rule_id']}.")
            if row.get("message") and (include_timestamps or include_ids):
                parts.append(f"Mesaj: {row.get('message')}.")
            return clean_answer(" ".join(parts), source_names)

        parts = [f"The latest aggregation run is for {row['rule_name']}."]
        if row.get("status"):
            parts.append(f"Status: {row.get('status')}.")
        if include_timestamps:
            parts.append(f"Started at: {row.get('started_at')}.")
            parts.append(f"Completed at: {row.get('completed_at')}.")
        if include_ids:
            parts.append(f"rule_id={row['rule_id']}.")
        if row.get("message") and (include_timestamps or include_ids):
            parts.append(f"Message: {row.get('message')}.")
        return clean_answer(" ".join(parts), source_names)

    return None


def _answer_looks_like_sql_leak(answer: str) -> bool:
    text = (answer or "").strip().lower()
    if not text:
        return False

    return any(
        token in text
        for token in (
            "select ",
            " from ",
            " join ",
            " where ",
            " order by ",
            " limit ",
            "```sql",
            "sql statement",
            "query pattern",
            "patterni kullanılabilir",
            "patterni kullanilabilir",
        )
    )


def _summarize_dp_row_for_user(row: dict[str, Any], question: str, max_fields: int = 4) -> str:
    include_ids = _question_requests_ids(question)
    include_timestamps = _question_requests_timestamps(question)
    parts: list[str] = []

    preferred_order = (
        "name",
        "rule_name",
        "formula_name",
        "bulk_formula_name",
        "group_name",
        "group_key",
        "status",
        "method",
        "interval_value",
        "interval_unit",
        "value",
        "result_value",
        "variable_name",
        "group_variable_name",
        "datapoint_id",
        "group_datapoint_id",
        "message",
        "note",
    )

    seen_keys: set[str] = set()
    ordered_keys = [key for key in preferred_order if key in row]
    ordered_keys.extend(key for key in row if key not in ordered_keys)

    for key in ordered_keys:
        if key in seen_keys:
            continue
        seen_keys.add(key)

        value = row.get(key)
        if value in (None, "", []):
            continue

        lowered = key.lower()
        if not include_ids and (lowered == "id" or lowered.endswith("_id")):
            continue
        if not include_timestamps and lowered in {"started_at", "completed_at", "created_at", "updated_at", "computed_at", "time"}:
            continue
        if lowered == "note":
            parts.append(str(value))
            continue

        label = lowered.replace("_", " ")
        parts.append(f"{label}: {value}")
        if len(parts) >= max_fields:
            break

    return "; ".join(parts) if parts else str(row)


def _build_generic_dp_db_rows_answer(
    question: str,
    dp_result: dict[str, Any],
    source_names: list[str],
    max_rows: int = 10,
) -> str | None:
    rows = dp_result.get("rows", [])
    if not rows:
        return None

    prefers_turkish = _question_prefers_turkish(question)
    domain = str(dp_result.get("domain") or "data").replace("+", "/")
    if prefers_turkish:
        lines = [f"{min(len(rows), max_rows)} adet {domain} kaydı bulundu:"]
    else:
        lines = [f"Returned {min(len(rows), max_rows)} {domain} row(s):"]

    for row in rows[:max_rows]:
        lines.append("- " + _summarize_dp_row_for_user(row, question))

    return clean_answer("\n".join(lines), source_names)


def _filter_package_web_results(
    question: str,
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    q = (question or "").lower()

    trusted_domains = (
        "npmjs.com",
        "github.com",
        "github.blog",
        "nvd.nist.gov",
        "osv.dev",
        "snyk.io",
    )

    exact_package = _extract_known_package_name(q)

    filtered = []
    trusted_results = []

    for result in results:
        domain = str(result.get("source") or "").lower().strip()
        url = str(result.get("url") or "").lower().strip()
        title = str(result.get("title") or "").lower().strip()
        content = str(result.get("content") or "").lower().strip()
        text = f"{url} {title} {content}"

        if any(domain == d or domain.endswith("." + d) for d in trusted_domains):
            trusted_results.append(result)
        else:
            continue

        npm_package_in_url = _extract_npm_package_from_url(url)

        if exact_package and "npmjs.com" in domain:
            if npm_package_in_url != exact_package:
                continue

        if exact_package == "left-pad":
            if "left-pad" not in text:
                continue

        elif exact_package == "leftpad":
            if "leftpad" not in text:
                continue

        elif exact_package:
            if exact_package not in text:
                continue

        filtered.append(result)

    if filtered:
        return filtered

    if trusted_results:
        return trusted_results[:3]

    return results[:3]



def _format_tools_used(sources_used: list[str]) -> str:
    labels = {
        "vector_db": "Vector DB",
        "data_processing_db": "Data Processing DB",
        "web_search": "Web Search",
    }
    return "\n".join(f"- {labels.get(tool, tool)}" for tool in sources_used)


def _normalize_answer_tools(answer: str, sources_used: list[str]) -> str:
    cleaned = (answer or "").strip()

    cleaned = re.sub(
        r"(?im)^\s*tools?_used\s*:\s*.*$\n?",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"(?im)^\s*tools\s*/\s*sources\s+used\s*:\s*.*$\n?",
        "",
        cleaned,
    )

    cleaned = re.sub(
        r"(?is)\n*\s*tools used\s*:.*?(?=\n\s*sources\s*:|\Z)",
        "",
        cleaned,
    ).strip()

    source_match = re.search(r"(?is)\n\s*sources\s*:", cleaned)
    tools_block = "Tools used:\n" + _format_tools_used(sources_used)

    if not source_match:
        return f"{cleaned}\n\n{tools_block}".strip()

    body = cleaned[:source_match.start()].strip()
    sources = cleaned[source_match.start():].strip()

    return f"{body}\n\n{tools_block}\n\n{sources}".strip()


def _direct_llm_response(
    question: str,
    total_start: float,
    tool_trace: list[dict[str, Any]],
    history: list[dict[str, Any]] | None = None,
    route: str = "direct_llm",
    reason: str = "The question was handled as a direct chat response without retrieval.",
) -> dict[str, Any]:
    memory_answer = _answer_from_chat_memory(question, history)
    if memory_answer:
        answer = memory_answer
    else:
        answer, _used_model = _call_direct_llm(question, history=history)

    return {
        "question": question,
        "answer": answer,
        "sources_used": ["llm"],
        "vector_queried_first": False,
        "model_used": PUBLIC_MODEL_ID,
        "tool_trace": tool_trace
        + [
            {
                "order": len(tool_trace) + 1,
                "tool": "llm",
                "used": True,
                "mode": "direct_chat",
            }
        ],
        "retrieved_chunks": [],
        "dp_db_results": [],
        "web_sources": [],
        "debug_trace": {
            "routing": {
                "route": route,
                "confidence": 1.0,
                "reason": reason,
                "model_used": PUBLIC_MODEL_ID,
            },
            "tool_trace": tool_trace
            + [
                {
                    "order": len(tool_trace) + 1,
                    "tool": "llm",
                    "used": True,
                    "mode": "direct_chat",
                }
            ],
            "sql_queries": [],
            "summary": {
                "sql_query_count": 0,
                "vector_match_count": 0,
                "dp_db_row_count": 0,
                "web_result_count": 0,
            },
        },
        "duration_ms": round((perf_counter() - total_start) * 1000, 1),
    }


def _build_debug_trace(
    *,
    route_decision: dict[str, Any],
    tool_trace: list[dict[str, Any]],
    dp_result: dict[str, Any],
    vector_matches: list[dict[str, Any]],
    web_results: list[dict[str, Any]],
) -> dict[str, Any]:
    sql_queries = list(dp_result.get("sql_debug_queries") or [])
    return {
        "routing": {
            "route": route_decision.get("route"),
            "confidence": route_decision.get("confidence"),
            "reason": route_decision.get("reason"),
            "model_used": route_decision.get("model_used"),
        },
        "tool_trace": tool_trace,
        "sql_queries": sql_queries,
        "summary": {
            "sql_query_count": len(sql_queries),
            "vector_match_count": len(vector_matches),
            "dp_db_row_count": len(dp_result.get("rows", [])),
            "web_result_count": len(web_results),
        },
    }



def answer_chat(
    question: str,
    top_k: int = 8,
    source: str | None = None,
    web_top_k: int = 5,
    history: list[dict[str, Any]] | None = None,
    conversation_context: str | None = None,
) -> dict[str, Any]:
    total_start = perf_counter()
    effective_source = _normalize_source_for_chat(source)
    effective_question = _build_effective_question(question, conversation_context)
    conversation_reference = _build_conversation_reference_block(conversation_context)
    internal_dp_db_candidate = _is_internal_dp_db_candidate(effective_question)
    if _should_skip_math_router(effective_question):
        math_route = {
            "ok": True,
            "model_used": "internal_dp_db_guard",
            "use_math_tool": False,
            "reason": "Skipped math routing because the question targets internal Data Processing DB records.",
            "raw_content": "",
            "fallback_used": False,
        }
    else:
        math_route = _route_question_for_math_tool(effective_question)
    if math_route.get("use_math_tool"):
        return _answer_with_math_tool(question, math_route)

    tool_trace = [
        {
            "order": 1,
            "tool": "math_router",
            "used": True,
            "result_count": 1,
            "decision": math_route.get("use_math_tool"),
            "reason": math_route.get("reason"),
        }
    ]

    if _should_answer_directly(question):
        return _direct_llm_response(
            question,
            total_start,
            tool_trace,
            history=history,
            route="direct_llm",
            reason="The question was classified as casual chat or direct conversation, so retrieval was skipped.",
        )

    vector_result = _query_vector_first(
        question=effective_question,
        top_k=top_k,
        source=effective_source,
    )
    vector_matches = vector_result["matches"]

    tool_trace.append(
        {
            "order": 2,
            "tool": "vector_db",
            "used": True,
            "result_count": len(vector_matches),
            "duration_ms": vector_result["duration_ms"],
            "error": vector_result["error"],
        }
    )

    route_decision = _route_question_with_llm(
        question=effective_question,
        vector_matches=vector_matches,
        conversation_context=conversation_context,
        source=effective_source,
    )
    guidance_only_matches = _guidance_only_vector_matches(effective_question, vector_matches)
    vector_evidence_sufficient = _vector_evidence_is_sufficient(
        effective_question,
        vector_matches,
        source=effective_source,
    )
    selected_route = str(route_decision.get("route") or "web")
    if _explicitly_requests_web(question):
        selected_route = "web"
        route_decision = {
            **route_decision,
            "route": "web",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.85),
            "reason": "The user explicitly requested a web lookup, so the question is routed to web search.",
        }
    elif _is_public_current_package_query(effective_question) and not effective_source:
        selected_route = "web"
        route_decision = {
            **route_decision,
            "route": "web",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.8),
            "reason": "Current public package version or advisory questions should be answered with web evidence.",
        }
    elif _is_public_general_knowledge_query(effective_question) and not effective_source:
        selected_route = "web"
        route_decision = {
            **route_decision,
            "route": "web",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.82),
            "reason": "Public general-knowledge questions should be answered with web evidence rather than direct model recall.",
        }
    elif _looks_like_public_civic_query(effective_question) and not effective_source:
        selected_route = "web"
        route_decision = {
            **route_decision,
            "route": "web",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.82),
            "reason": "Public civic and demographic questions should be answered with web evidence rather than direct model recall.",
        }
    elif internal_dp_db_candidate:
        selected_route = "vector_and_dp_db"
        route_decision = {
            **route_decision,
            "route": "vector_and_dp_db",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.9),
            "reason": "The question targets internal app modules or records, so it should use Vector DB guidance plus read-only Data Processing DB lookup instead of web search.",
        }
    elif (guidance_only_matches or not vector_evidence_sufficient) and selected_route != "web" and not effective_source:
        selected_route = "web"
        route_decision = {
            **route_decision,
            "route": "web",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.78),
            "reason": "Internal vector evidence is not sufficient, so the question is routed to web search.",
        }
    public_web_only = selected_route == "web"
    use_dp_db = selected_route == "vector_and_dp_db"
    use_web = selected_route == "web"

    tool_trace.append(
        {
            "order": 2,
            "tool": "llm_router",
            "used": True,
            "result": selected_route,
            "confidence": route_decision.get("confidence"),
            "top_similarity": route_decision.get("top_similarity"),
            "model": route_decision.get("model_used"),
            "reason": route_decision.get("reason"),
        }
    )

    if not use_dp_db and not use_web and not _has_relevant_vector_match(vector_matches):
        return _direct_llm_response(
            question,
            total_start,
            tool_trace,
            history=history,
            route="direct_llm_after_low_evidence",
            reason="Retrieval did not produce strong enough evidence for vector or web routing, so the assistant fell back to direct chat.",
        )

    dp_result = {
        "ok": True,
        "rows": [],
    }
    dp_context = ""

    if use_dp_db:
        dp_result = query_internal_data(effective_question)
        dp_context = build_dp_db_context(dp_result)

    tool_trace.append(
        {
            "order": 3,
            "tool": "data_processing_db",
            "used": use_dp_db,
            "result_count": len(dp_result.get("rows", [])),
            "error": None if dp_result.get("ok") else dp_result.get("error"),
        }
    )

    web_results = []
    web_context = ""

    if use_web:
        web_query = _build_web_query(effective_question)
        web_results = web_search(web_query, max_results=web_top_k)
        web_results = _rerank_web_results(effective_question, web_results)[:web_top_k]
        web_results = _filter_package_web_results(effective_question, web_results)
        web_context = build_web_context(web_results)

        if not web_results:
            logger.info("orchestrator_web_search_empty query=%r rewritten_query=%r", question, web_query)


    tool_trace.append(
        {
            "order": 4,
            "tool": "web_search",
            "used": use_web,
            "result_count": len(web_results),
        }
    )

    debug_trace = _build_debug_trace(
        route_decision=route_decision,
        tool_trace=tool_trace,
        dp_result=dp_result,
        vector_matches=vector_matches,
        web_results=web_results,
    )

    if public_web_only:
        sources_used = ["web_search"]
    else:
        sources_used = ["vector_db"]
        if use_dp_db:
            sources_used.append("data_processing_db")
        if use_web:
            sources_used.append("web_search")

    context_parts = []

    if conversation_reference:
        context_parts.append(conversation_reference)

    if not public_web_only:
        vector_context_text = vector_result.get("context") or "No vector matches."
        if use_dp_db:
            vector_context_text = (
                "This question targets internal Data Processing records. "
                "Use Data Processing DB rows for exact counts, statuses, timestamps, mappings, and snapshots. "
                "Use Vector DB only as routing and schema guidance."
            )
        context_parts.append(
            "VECTOR DB CONTEXT:\n"
            + vector_context_text
        )

    if use_dp_db:
        context_parts.append("DATA PROCESSING DB CONTEXT:\n" + dp_context)

    if use_web:
        context_parts.append("WEB SEARCH CONTEXT:\n" + web_context)

    combined_context = "\n\n====================\n\n".join(context_parts)
    combined_context = (
        "TOOLS_USED:\n"
        + ", ".join(sources_used)
        + "\n\n====================\n\n"
        + combined_context
    )

    source_names: list[str] = []
    if not public_web_only:
        source_names.extend(_build_vector_source_names(vector_matches))
        if use_dp_db:
            source_names.append("Data Processing DB")

    if use_web:
        for item in _build_web_source_names(web_results):
            if item not in source_names:
                source_names.append(item)

    deterministic_web_answer = None
    if use_web:
        deterministic_web_answer = _build_deterministic_package_web_answer(
            question=effective_question,
            web_results=web_results,
            source_names=source_names,
        )
        if deterministic_web_answer:
            answer = _normalize_answer_tools(deterministic_web_answer, sources_used)
            return {
                "question": question,
                "answer": answer,
                "sources_used": sources_used,
                "vector_queried_first": True,
                "model_used": "deterministic_package_web_formatter",
                "routing_decision": route_decision,
                "tool_trace": tool_trace,
                "retrieved_chunks": vector_matches,
                "dp_db_results": dp_result.get("rows", []),
                "web_sources": _public_web_results(web_results),
                "debug_trace": debug_trace,
                "duration_ms": round((perf_counter() - total_start) * 1000, 1),
            }

    deterministic_dp_db_answer = None
    if use_dp_db:
        deterministic_dp_db_answer = _build_deterministic_dp_db_answer(
            question=effective_question,
            dp_result=dp_result,
            source_names=source_names,
        )
        if deterministic_dp_db_answer:
            answer = _normalize_answer_tools(deterministic_dp_db_answer, sources_used)
            return {
                "question": question,
                "answer": answer,
                "sources_used": sources_used,
                "vector_queried_first": True,
                "model_used": "deterministic_dp_db_formatter",
                "routing_decision": route_decision,
                "tool_trace": tool_trace,
                "retrieved_chunks": vector_matches,
                "dp_db_results": dp_result.get("rows", []),
                "web_sources": _public_web_results(web_results),
                "debug_trace": debug_trace,
                "duration_ms": round((perf_counter() - total_start) * 1000, 1),
            }

    answer, used_model = _call_llm(
        question=question,
        context=combined_context,
        source_names=source_names,
        history=history,
    )
    if use_dp_db and dp_result.get("rows") and _answer_looks_like_sql_leak(answer):
        fallback_answer = _build_generic_dp_db_rows_answer(
            question=effective_question,
            dp_result=dp_result,
            source_names=source_names,
        )
        if fallback_answer:
            answer = fallback_answer
            used_model = "deterministic_dp_db_sql_leak_guard"
    answer = _normalize_answer_tools(answer, sources_used)

    return {
        "question": question,
        "answer": answer,
        "sources_used": sources_used,
        "vector_queried_first": True,
        "model_used": used_model,
        "routing_decision": route_decision,
        "tool_trace": tool_trace,
        "retrieved_chunks": vector_matches,
        "dp_db_results": dp_result.get("rows", []),
        "web_sources": _public_web_results(web_results),
        "debug_trace": debug_trace,
        "duration_ms": round((perf_counter() - total_start) * 1000, 1),
    }
