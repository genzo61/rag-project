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

def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = (text or "").lower()
    return any(phrase in lowered for phrase in phrases)

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
    q = (question or "").lower()

    question_needs_db = any(
        keyword in q
        for keyword in (
            "audit",
            "audit history",
            "hidden metadata",
            "metadata",
            "processing failure",
            "processing failures",
            "why did",
            "failure",
            "failed",
            "validation",
            "validation result",
            "validation results",
            "cross-reference",
            "cross reference",
            "internal",
            "join",
            "owner",
            "package processing",
            "processing job",
            "processing status",
            "quarantine",
            "quarantined",
        )
    )

    if not question_needs_db:
        return False

    return True



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

    if "lodash" in q:
        return "lodash npm latest version security advisory"
    if "left-pad" in q and "left-pad" not in q and "leftpad" not in q:
        return "left-pad npm latest version"
    if "leftpad" in q and "left-pad" not in q and "leftpad" not in text:
        return "left-pad npm latest version"
    if "event-stream" in q:
        return "event-stream npm latest version security advisory"

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



def answer_chat(
    question: str,
    top_k: int = 8,
    source: str | None = None,
    web_top_k: int = 5,
) -> dict[str, Any]:
    total_start = perf_counter()
    tool_trace = []

    vector_result = _query_vector_first(
        question=question,
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

    use_dp_db = _needs_dp_db(question, vector_matches)
    use_web = _needs_web(question, vector_matches)

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
        web_query = _build_web_query(question)
        web_results = web_search(web_query, max_results=web_top_k)
        web_results = _rerank_web_results(question, web_results)[:web_top_k]
        web_results = _filter_package_web_results(question, web_results)
        web_context = build_web_context(web_results)


    tool_trace.append(
        {
            "order": 3,
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

    context_parts = [
        "VECTOR DB CONTEXT:\n"
        + (vector_result.get("context") or "No vector matches.")
    ]

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

    if use_dp_db:
        source_names.append("Data Processing DB")

    if use_web:
        source_names.extend(_build_web_source_names(web_results))

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
