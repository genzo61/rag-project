import json
import re
import logging
from time import perf_counter
from typing import Any, cast


from .db import count_documents
from .dp_db import build_dp_db_context, query_internal_data
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
from .math_tool_orchestrator import run_math_tool_conversation

logger = logging.getLogger("rag.orchestrator")

PUBLIC_MODEL_ID = "local-rag"

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

WEB_KEYWORDS = (
    "latest",
    "current",
    "today",
    "now",
    "recent",
    "release",
    "cve",
    "vulnerability",
    "security advisory",
    "npmjs",
    "github",
    "güncel",
    "guncel",
    "son sürüm",
    "son surum",
    "bugün",
    "bugun",
)

DP_VECTOR_HINTS = (
    "query the data processing db",
    "requires querying the data processing db",
    "structured internal data",
    "structured/internal data",
    "structured/internal facts",
    "internal structured data",
    "audit history",
    "hidden metadata",
    "processing failures",
    "validation results",
    "cross-reference",
    "cross reference",
    "npm package processing jobs",
)

WEB_VECTOR_HINTS = (
    "query web search",
    "requires web search",
    "external or current data",
    "external/current data",
    "external or current facts",
    "current external data",
    "current facts",
    "latest npm package versions",
    "current cves",
    "current release notes",
    "security advisories",
    "recent ecosystem information",
)

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
        return None
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
                "answer": str(result.get("formatted_result") or result.get("result")),
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
        "answer": str(result.get("formatted_result") or result.get("result")),
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
                    }
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
            }
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
    asks_package = any(token in q for token in PACKAGE_HINTS)
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

def _vector_requests_dp_db(vector_matches: list[dict[str, Any]]) -> bool:
    vector_blob = _relevant_vector_blob(vector_matches)
    return _contains_any(vector_blob, DP_VECTOR_HINTS)

def _vector_requests_web(vector_matches: list[dict[str, Any]]) -> bool:
    vector_blob = _relevant_vector_blob(vector_matches)
    return _contains_any(vector_blob, WEB_VECTOR_HINTS)


def _relevant_vector_blob(
    vector_matches: list[dict[str, Any]],
    min_similarity: float = 0.18,
) -> str:
    relevant = []

    for match in vector_matches:
        try:
            similarity = float(match.get("similarity", 0.0))
        except Exception:
            similarity = 0.0

        if similarity >= min_similarity:
            relevant.append(str(match.get("content", "")))

    return " ".join(relevant).lower()


# def _needs_dp_db(question: str, vector_matches: list[dict[str, Any]]) -> bool:
#     q = (question or "").lower()
#     vector_blob = _relevant_vector_blob(vector_matches)

#     question_needs_db = any(keyword in q for keyword in DP_DB_KEYWORDS)
#     vector_says_db = any(
#         phrase in vector_blob
#         for phrase in (
#             "requires querying the data processing db",
#             "query the data processing db",
#             "internal structured data",
#             "structured/internal facts",
#             "audit history",
#             "hidden metadata",
#             "processing failures",
#             "validation results",
#             "cross-reference",
#             "cross reference",
#         )
#     )

#     return question_needs_db or vector_says_db

def _needs_dp_db(question: str, vector_matches: list[dict[str, Any]]) -> bool:
    q = (question or "").lower().strip()

    if (
        _is_public_current_package_query(question)
        or _explicitly_requests_web(question)
        or _is_general_math_formula_query(question)
    ):
        return False

    architecture_patterns = (
        "how does",
        "how do",
        "what is the role",
        "what is the purpose",
        "how are",
        "how is",
        "workflow",
        "architecture",
        "at an architecture level",
        "interaction between",
        "interact with",
        "how formulas",
        "how validations",
        "how aggregations",
    )

    structured_internal_patterns = (
        "audit",
        "audit history",
        "hidden metadata",
        "metadata",
        "processing failure",
        "processing failures",
        "why did",
        "failure",
        "failed",
        "validation result",
        "validation results",
        "cross-reference",
        "cross reference",
        "internal status",
        "processing status",
        "quarantine",
        "quarantined",
        "which job",
        "which jobs",
        "which run",
        "which runs",
        "which package",
        "specific run",
        "specific job",
        "specific record",
        "count",
        "counts",
        "processed count",
        "inserted count",
        "message",
        "owner",
        "details",
    )

    if any(pattern in q for pattern in structured_internal_patterns):
        return True

    if any(pattern in q for pattern in architecture_patterns):
        return False

    vector_blob = _relevant_vector_blob(vector_matches)

    vector_requests_db = any(
        phrase in vector_blob
        for phrase in (
            "query the data processing db",
            "structured aggregation run details",
            "audit history",
            "execution status",
            "processed counts",
            "inserted counts",
            "run messages",
            "structured internal records",
            "internal metadata",
        )
    )

    return vector_requests_db



# def _needs_web(question: str, vector_matches: list[dict[str, Any]]) -> bool:
#     q = (question or "").lower()
#     vector_blob = _relevant_vector_blob(vector_matches)

#     question_needs_web = any(keyword in q for keyword in WEB_KEYWORDS)
#     vector_says_web = any(
#         phrase in vector_blob
#         for phrase in (
#             "requires web search",
#             "query web search",
#             "external/current data",
#             "external or current facts",
#             "external facts",
#             "current facts",
#             "current data",
#         )
#     )

#     return question_needs_web or vector_says_web

def _needs_web(question: str, vector_matches: list[dict[str, Any]]) -> bool:
    q = (question or "").lower()

    if _explicitly_requests_web(question) or _is_general_math_formula_query(question):
        return True

    question_needs_web = any(
        keyword in q
        for keyword in (
            "latest",
            "current",
            "today",
            "now",
            "recent",
            "release",
            "cve",
            "vulnerability",
            "security advisory",
            "npmjs",
            "github",
            "güncel",
            "guncel",
            "son sürüm",
            "son surum",
            "bugün",
            "bugun",
        )
    )

    if not question_needs_web:
        return False

    return True


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
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "You are the Data Processing App chat assistant.\n"
                "Use only the provided context.\n"
                "The vector database is always the first source of truth.\n"
                "If DP DB context exists, use it for structured/internal facts.\n"
                "If web context exists, use it only for external or current facts.\n"
                "Only mention tools listed under TOOLS_USED.\n"
                "Do not claim DP DB or web search was used unless it appears in TOOLS_USED.\n"
                "Do not invent missing facts.\n"
                "Keep the answer concise.\n"
                "Mention which tools/sources were used."
                "Do not print the TOOLS_USED block verbatim.\n"
                "Do not invent versions, CVEs, advisories, dates, or release notes.\n"
                "If a version or CVE is not explicitly present in the context, say it was not verified from the provided sources.\n"
                "Use concise wording; do not say 'Queryed'.\n"
                "If web_search appears in TOOLS_USED, you must summarize the WEB SEARCH CONTEXT.\n"
                "Never say web search was not queried when web_search appears in TOOLS_USED.\n"
                "If data_processing_db appears in TOOLS_USED, summarize the DP DB context.\n"
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

    if "lodash" in q:
        return "lodash npm latest version security advisory"
    if "left-pad" in q:
        return "left-pad npm latest version"
    if "leftpad" in q:
        return "left-pad npm latest version"
    if "event-stream" in q:
        return "event-stream npm latest version security advisory"
    if "is-number" in q:
        return "is-number npm latest version security advisory"

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

    exact_package = None
    if "left-pad" in q:
        exact_package = "left-pad"
    elif re.search(r"\bleftpad\b", q):
        exact_package = "leftpad"
    elif "lodash" in q:
        exact_package = "lodash"
    elif "event-stream" in q:
        exact_package = "event-stream"
    elif "is-number" in q:
        exact_package = "is-number"

    filtered = []

    for result in results:
        domain = str(result.get("source") or "").lower().strip()
        url = str(result.get("url") or "").lower().strip()
        title = str(result.get("title") or "").lower().strip()
        content = str(result.get("content") or "").lower().strip()
        text = f"{url} {title} {content}"

        if not any(domain == d or domain.endswith("." + d) for d in trusted_domains):
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

    return filtered or results[:3]



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
        "duration_ms": round((perf_counter() - total_start) * 1000, 1),
    }



def answer_chat(
    question: str,
    top_k: int = 8,
    source: str | None = None,
    web_top_k: int = 5,
    history: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    total_start = perf_counter()
    if _is_math_tool_candidate(question):
        math_route = {
            "ok": True,
            "use_math_tool": True,
            "reason": "deterministic math candidate",
        }
    else:
        math_route = {
            "ok": True,
            "use_math_tool": False,
            "reason": "not a math tool candidate",
        }

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
        return _direct_llm_response(question, total_start, tool_trace, history=history)

    vector_result = _query_vector_first(
        question=question,
        top_k=top_k,
        source=source,
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

    use_dp_db = _needs_dp_db(question, vector_matches)
    use_web = _needs_web(question, vector_matches)
    explicit_web_request = _explicitly_requests_web(question)

    math_formula_request = _is_general_math_formula_query(question)

    if _is_public_current_package_query(question) or explicit_web_request or math_formula_request:
        use_web = True
        use_dp_db = False

    if not use_dp_db and not use_web and not _has_relevant_vector_match(vector_matches):
        return _direct_llm_response(question, total_start, tool_trace, history=history)

    dp_result = {
        "ok": True,
        "rows": [],
    }
    dp_context = ""

    if use_dp_db:
        dp_result = query_internal_data(question)
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
        web_query = _build_web_query(question)
        web_results = web_search(web_query, max_results=web_top_k)
        web_results = _rerank_web_results(question, web_results)[:web_top_k]
        web_results = _filter_package_web_results(question, web_results)
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

    sources_used = ["vector_db"]

    if use_dp_db:
        sources_used.append("data_processing_db")

    if use_web:
        sources_used.append("web_search")

    vector_context = vector_result.get("context") or "No vector matches."
    if (explicit_web_request or math_formula_request) and use_web and not use_dp_db:
        vector_context = (
            "Vector DB was checked first for routing guidance. "
            "Answer this request from WEB SEARCH CONTEXT unless the web results are insufficient."
        )

    context_parts = ["VECTOR DB CONTEXT:\n" + vector_context]

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

    source_names = _build_vector_source_names(vector_matches)
    if (explicit_web_request or math_formula_request) and use_web and not use_dp_db:
        source_names = ["Vector DB (routing only)"]

    if use_dp_db:
        source_names.append("Data Processing DB")

    if use_web:
        source_names.extend(_build_web_source_names(web_results))

    answer, used_model = _call_llm(
        question=question,
        context=combined_context,
        source_names=source_names,
        history=history,
    )
    answer = _normalize_answer_tools(answer, sources_used)

    return {
        "question": question,
        "answer": answer,
        "sources_used": sources_used,
        "vector_queried_first": True,
        "model_used": PUBLIC_MODEL_ID,
        "tool_trace": tool_trace,
        "retrieved_chunks": vector_matches,
        "dp_db_results": dp_result.get("rows", []),
        "web_sources": _public_web_results(web_results),
        "duration_ms": round((perf_counter() - total_start) * 1000, 1),
    }
