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
    retrieve_context,
    web_search,
)
from .math_tool_orchestrator import run_math_tool_conversation

logger = logging.getLogger("rag.orchestrator")

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
    asks_how = any(token in q for token in ("how", "nedir", "nasil", "nasıl", "formula", "calculate", "find"))
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

    if any(
        token in q
        for token in (
            "cve",
            "github",
            "validation result",
            "audit history",
            "processing job",
            "water main",
            "crli",
            "ili",
        )
    ):
        return False

    if _is_general_math_formula_query(question):
        return True

    has_math_symbols = bool(re.search(r"\d", q) and re.search(r"[\+\-\*/%=()]", q))
    has_math_language = any(term in q for term in GENERAL_MATH_TASK_TERMS)
    return has_math_symbols or has_math_language


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
            response = client.chat.completions.create(
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


def _answer_with_math_tool(question: str, route_info: dict[str, Any]) -> dict[str, Any]:
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

            return {
                "question": question,
                "answer": answer or "I could not produce a math answer.",
                "sources_used": ["math_tool"] if tool_called else [],
                "vector_queried_first": False,
                "model_used": model_name,
                "tool_trace": [
                    {
                        "order": 1,
                        "tool": "math_router",
                        "used": True,
                        "result_count": 1,
                        "router_model": route_info.get("model_used"),
                        "fallback_used": route_info.get("fallback_used", False),
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

    return {
        "question": question,
        "answer": f"Temporary math tool error: {last_error}",
        "sources_used": [],
        "vector_queried_first": False,
        "model_used": PRIMARY_LLM_MODEL,
        "tool_trace": [
            {
                "order": 1,
                "tool": "math_router",
                "used": True,
                "result_count": 1,
                "router_model": route_info.get("model_used"),
                "fallback_used": route_info.get("fallback_used", False),
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
            response = client.chat.completions.create(
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
            response = client.chat.completions.create(
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


def _call_llm(
    question: str,
    context: str,
    source_names: list[str],
) -> tuple[str, str]:
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
            ),
        },
        {
            "role": "user",
            "content": f"Question:\n{question}\n\nContext:\n{context}",
        },
    ]

    last_error = None
    used_model = ""

    for model in _build_model_candidates():
        used_model = model
        try:
            response = client.chat.completions.create(
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



def answer_chat(
    question: str,
    top_k: int = 8,
    source: str | None = None,
    web_top_k: int = 5,
    conversation_context: str | None = None,
) -> dict[str, Any]:
    total_start = perf_counter()
    effective_source = _normalize_source_for_chat(source)
    effective_question = _build_effective_question(question, conversation_context)
    conversation_reference = _build_conversation_reference_block(conversation_context)
    math_route = _route_question_for_math_tool(effective_question)
    if math_route.get("use_math_tool"):
        return _answer_with_math_tool(question, math_route)

    tool_trace = [
        {
            "order": 1,
            "tool": "math_router",
            "used": True,
            "result_count": 1,
            "router_model": math_route.get("model_used"),
            "fallback_used": math_route.get("fallback_used", False),
            "decision": math_route.get("use_math_tool"),
            "reason": math_route.get("reason"),
        }
    ]

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
    if (guidance_only_matches or not vector_evidence_sufficient) and selected_route != "web" and not effective_source:
        selected_route = "web"
        route_decision = {
            **route_decision,
            "route": "web",
            "confidence": max(float(route_decision.get("confidence", 0.0) or 0.0), 0.78),
            "reason": "Internal vector evidence is not sufficient, so the question is routed to web search.",
        }
    elif _explicitly_requests_web(question):
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
        context_parts.append(
            "VECTOR DB CONTEXT:\n"
            + (vector_result.get("context") or "No vector matches.")
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
                "duration_ms": round((perf_counter() - total_start) * 1000, 1),
            }

    answer, used_model = _call_llm(
        question=question,
        context=combined_context,
        source_names=source_names,
    )
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
        "duration_ms": round((perf_counter() - total_start) * 1000, 1),
    }
