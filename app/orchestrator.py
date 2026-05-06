import re
import logging
from time import perf_counter
from typing import Any, cast


from .db import count_documents
from .dp_db import build_dp_db_context, query_internal_data
from .rag import (
    _build_model_candidates,
    _public_web_results,
    _rerank_web_results,
    build_web_context,
    clean_answer,
    client,
    retrieve_context,
    web_search,
)

logger = logging.getLogger("rag.orchestrator")

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
    "npm",
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

PUBLIC_INFO_PATTERNS = (
    "how old",
    "kaç yaş",
    "kaç yaşında",
    "kimdir",
    "kim bu",
    "who is",
    "where is",
    "where does",
    "hangi takım",
    "which team",
    "president",
    "prime minister",
    "capital of",
    "nerede",
    "nereli",
    "doğum tarihi",
    "birth date",
    "birthday",
    "married",
    "spouse",
)

INTERNAL_APP_PATTERNS = (
    "data processing",
    "vector db",
    "dp db",
    "our app",
    "our system",
    "internal",
    "aggregation",
    "formula",
    "datapoint",
    "validation",
    "audit",
    "metadata",
    "processing job",
    "processing status",
)

def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in phrases)


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


def _has_strong_vector_match(vector_matches: list[dict[str, Any]], threshold: float = 0.32) -> bool:
    for match in vector_matches:
        try:
            similarity = float(match.get("similarity", 0.0))
        except Exception:
            similarity = 0.0
        if similarity >= threshold:
            return True
    return False


def _looks_like_internal_app_question(question: str, vector_matches: list[dict[str, Any]]) -> bool:
    q = (question or "").lower()
    if any(pattern in q for pattern in INTERNAL_APP_PATTERNS):
        return True
    return False


def _looks_like_public_info_question(question: str) -> bool:
    q = (question or "").lower().strip()
    if not q:
        return False

    if any(pattern in q for pattern in PUBLIC_INFO_PATTERNS):
        return True

    if "?" in q and not any(pattern in q for pattern in INTERNAL_APP_PATTERNS):
        if any(token in q for token in ("kim", "kaç", "hangi", "where", "who", "when", "age", "yaş")):
            return True

    return False


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
    if _vector_requests_web(vector_matches):
        return True

    if _looks_like_public_info_question(q) and not _looks_like_internal_app_question(q, vector_matches):
        return True

    package_name = _extract_known_package_name(q)
    package_public_signal = any(
        phrase in q
        for phrase in (
            "npm",
            "package",
            "latest version",
            "version",
            "advisory",
            "vulnerability",
            "security",
        )
    )

    if package_name and package_public_signal:
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
    q = (question or "").lower()
    security_lookup = any(token in q for token in ("security", "advisory", "vulnerability", "cve"))
    version_lookup = any(token in q for token in ("latest", "version", "npm"))
    package_name = _extract_known_package_name(q)

    if package_name:
        if security_lookup:
            return f"{package_name} npm security advisory vulnerability cve"
        if version_lookup:
            return f"{package_name} npm latest version"
        return f"{package_name} npm package"

    if "left-pad" in q and "left-pad" not in q and "leftpad" not in q:
        return "left-pad npm latest version"
    if "leftpad" in q and "left-pad" not in q:
        return "left-pad npm latest version"

    return question



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
    tool_trace = []
    effective_question = _build_effective_question(question, conversation_context)
    conversation_reference = _build_conversation_reference_block(conversation_context)
    public_web_only = _looks_like_public_info_question(effective_question) and not _looks_like_internal_app_question(effective_question, [])

    vector_result = _query_vector_first(
        question=effective_question,
        top_k=top_k,
        source=source,
    )
    vector_matches = vector_result["matches"]

    tool_trace.append(
        {
            "order": 1,
            "tool": "vector_db",
            "used": True,
            "result_count": len(vector_matches),
            "duration_ms": vector_result["duration_ms"],
            "error": vector_result["error"],
        }
    )

    use_dp_db = False if public_web_only else _needs_dp_db(effective_question, vector_matches)
    use_web = _needs_web(effective_question, vector_matches)

    dp_result = {
        "ok": True,
        "rows": [],
    }
    dp_context = ""

    if use_dp_db:
        dp_result = query_internal_data(effective_question)
        dp_context = build_dp_db_context(dp_result)

    # If internal retrieval is weak and the question does not look internal,
    # fall back to public web search even when the initial keyword heuristic missed it.
    if not use_web:
        strong_vector_match = _has_strong_vector_match(vector_matches)
        has_dp_rows = bool(dp_result.get("rows"))
        if (not strong_vector_match and not has_dp_rows) and not _looks_like_internal_app_question(effective_question, vector_matches):
            use_web = True

    public_web_only = use_web and _looks_like_public_info_question(effective_question) and not _looks_like_internal_app_question(effective_question, vector_matches)

    tool_trace.append(
        {
            "order": 2,
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


    tool_trace.append(
        {
            "order": 3,
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
        "tool_trace": tool_trace,
        "retrieved_chunks": vector_matches,
        "dp_db_results": dp_result.get("rows", []),
        "web_sources": _public_web_results(web_results),
        "duration_ms": round((perf_counter() - total_start) * 1000, 1),
    }
