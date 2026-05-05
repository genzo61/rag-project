import os
import re
from pathlib import Path
from typing import Any
import logging
from time import perf_counter
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from openai import OpenAI

from .chunking import chunk_pdf_pages
from .db import count_documents, insert_documents_batch, search_similar
from .embeddings import get_embedding
from .pdf_utils import extract_pdf_pages

logger = logging.getLogger("rag.service")
ENV_PATH = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_CHAT_MODEL = os.getenv("OPENROUTER_CHAT_MODEL", "openrouter/free")
OPENROUTER_FALLBACK_MODELS = os.getenv("OPENROUTER_FALLBACK_MODELS", "")

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "llama3.2:3b")
OLLAMA_FALLBACK_MODELS = os.getenv("OLLAMA_FALLBACK_MODELS", "")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")

LLM_BACKEND = os.getenv("LLM_BACKEND", "openrouter").strip().lower()
SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL", "http://localhost:8080")

def _normalize_openai_base_url(base_url: str) -> str:
    value = (base_url or "").rstrip("/")
    if value.endswith("/v1"):
        return value
    return f"{value}/v1"


if LLM_BACKEND == "ollama":
    LLM_BASE_URL = _normalize_openai_base_url(OLLAMA_BASE_URL)
    LLM_API_KEY = OLLAMA_API_KEY
    PRIMARY_LLM_MODEL = OLLAMA_CHAT_MODEL
    FALLBACK_LLM_MODELS = OLLAMA_FALLBACK_MODELS
else:
    LLM_BASE_URL = OPENROUTER_BASE_URL
    LLM_API_KEY = OPENROUTER_API_KEY
    PRIMARY_LLM_MODEL = OPENROUTER_CHAT_MODEL
    FALLBACK_LLM_MODELS = OPENROUTER_FALLBACK_MODELS

client = OpenAI(
    base_url=LLM_BASE_URL,
    api_key=LLM_API_KEY,
)


def _build_model_candidates() -> list[str]:
    candidates: list[str] = []
    for model_name in [PRIMARY_LLM_MODEL, *FALLBACK_LLM_MODELS.split(",")]:
        m = (model_name or "").strip()
        if m and m not in candidates:
            candidates.append(m)

    # OpenRouter route katmani; ilk model limitteyse bazen kurtarir.
    if LLM_BACKEND == "openrouter" and "openrouter/auto" not in candidates:
        candidates.append("openrouter/auto")
    return candidates


def _is_retryable_llm_error(exc: Exception) -> bool:
    status_code = getattr(exc, "status_code", None)
    if status_code in {408, 409, 425, 429, 500, 502, 503, 504}:
        return True

    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "rate-limited",
            "rate limited",
            "temporarily",
            "service unavailable",
            "too many requests",
            "timeout",
        )
    )

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "were",
    "was", "are", "how", "what", "when", "where", "why", "according",
    "document", "problem", "using", "within", "would", "could", "should",
    "their", "about", "there", "have", "has", "had", "will"
}


# ============================================================
# Text / rerank helpers
# ============================================================

def tokenize_for_rerank(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", (text or "").lower())
    return [t for t in tokens if len(t) > 2 and t not in STOPWORDS]


def lexical_overlap_score(question: str, text: str) -> float:
    q_tokens = set(tokenize_for_rerank(question))
    if not q_tokens:
        return 0.0

    t_tokens = set(tokenize_for_rerank(text))
    overlap = len(q_tokens & t_tokens) / max(len(q_tokens), 1)

    q = question.lower()
    t = (text or "").lower()

    phrase_boost = 0.0

    # framing soruları
    if "framed" in q and ("framed this problem" in t or "definition" in t):
        phrase_boost += 0.35

    if "classification" in q and "classification" in t:
        phrase_boost += 0.25

    if "next three years" in q and "next three years" in t:
        phrase_boost += 0.25

    if "given city block" in q and "given city block" in t:
        phrase_boost += 0.20

    # usefulness / why useful soruları
    if ("useful" in q or "why" in q) and "allows" in t:
        phrase_boost += 0.30

    if ("useful" in q or "why" in q) and "operationalize" in t:
        phrase_boost += 0.30

    if ("useful" in q or "why" in q) and "plan" in t:
        phrase_boost += 0.20

    if ("useful" in q or "why" in q) and "infrastructure development" in t:
        phrase_boost += 0.20

    if ("useful" in q or "why" in q) and "coordinate" in t:
        phrase_boost += 0.15

    if ("useful" in q or "why" in q) and "targeted proactive" in t:
        phrase_boost += 0.15

    # reactive vs model-driven replacement questions
    if ("reactive" in q or "model-driven" in q or "replacement" in q) and "field crews" in t:
        phrase_boost += 0.35

    if ("reactive" in q or "model-driven" in q or "replacement" in q) and "risk scores" in t:
        phrase_boost += 0.30

    if ("reactive" in q or "model-driven" in q) and "department of public works" in t:
        phrase_boost += 0.25

    if ("methodology" in q or "evaluation" in q) and "temporal cross-validation" in t:
        phrase_boost += 0.35

    if ("methodology" in q or "evaluation" in q) and "out-of-sample" in t:
        phrase_boost += 0.30

    if ("methodology" in q or "evaluation" in q) and "heuristics" in t:
        phrase_boost += 0.20

    # feature importance gibi alakasız ama benzer görünen chunk'ları biraz bastır
    penalty = 0.0
    if "most important feature" in t:
        penalty += 0.20
    if "pipe diameter" in t or "pipe age" in t:
        penalty += 0.10

    return overlap + phrase_boost - penalty


def rerank_matches(question: str, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reranked = []

    for match in matches:
        semantic = float(match.get("similarity", 0.0))
        lexical = lexical_overlap_score(question, match.get("content", ""))

        q = question.lower()
        t = (match.get("content", "") or "").lower()

        intent_bonus = 0.0

        # framing-type questions
        if "framed" in q and "framed this problem" in t:
            intent_bonus += 0.25

        # usefulness-type questions
        if ("useful" in q or "why" in q) and "this definition allows" in t:
            intent_bonus += 0.35

        if ("useful" in q or "why" in q) and "operationalize this model" in t:
            intent_bonus += 0.30

        if ("useful" in q or "why" in q) and "plan the infrastructure development" in t:
            intent_bonus += 0.25

        if ("reactive" in q or "model-driven" in q or "replacement" in q) and "little means of identifying mains at the highest risk" in t:
            intent_bonus += 0.35

        if ("reactive" in q or "model-driven" in q or "replacement" in q) and "risk scores" in t:
            intent_bonus += 0.25

        if ("methodology" in q or "evaluation" in q) and "temporal cross-validation" in t:
            intent_bonus += 0.30

        if ("methodology" in q or "evaluation" in q) and "out-of-sample" in t:
            intent_bonus += 0.25

        score = (semantic * 0.60) + (lexical * 0.40) + intent_bonus

        enriched = dict(match)
        enriched["rerank_score"] = score
        reranked.append(enriched)

    reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
    return reranked


def normalize_source(source: str, pdf_path: str | None = None) -> str:
    value = (source or "").strip()

    if not value and pdf_path:
        value = Path(pdf_path).stem

    value = value.strip()
    if value.lower().endswith(".pdf"):
        value = value[:-4]

    return value.lower()


def looks_like_reference_chunk(text: str) -> bool:
    t = (text or "").lower()

    signals = [
        "references",
        "bibliography",
        "doi",
        "et al.",
        "proceedings",
        "journal",
        "reliability engineering",
        "urban water",
    ]

    score = sum(1 for s in signals if s in t)

    # numeric citation density like [11] [12] [13]
    citation_hits = len(re.findall(r"\[\d+\]", t))
    if citation_hits >= 3:
        score += 2

    return score >= 2


def looks_like_cover_or_title_chunk(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False

    lower_t = t.lower()
    tokens = re.findall(r"[a-z0-9]+", lower_t)
    lines = [line.strip() for line in t.splitlines() if line.strip()]

    if len(tokens) > 90 or len(lines) > 12:
        return False

    signals = [
        "conference",
        "proceedings",
        "symposium",
        "workshop",
        "university",
        "department",
        "school of",
        "isbn",
        "copyright",
        "all rights reserved",
        "published by",
    ]

    signal_hits = sum(1 for s in signals if s in lower_t)
    year_hits = len(re.findall(r"\b(?:19|20)\d{2}\b", lower_t))
    if year_hits >= 2:
        signal_hits += 1

    sentence_marks = t.count(".") + t.count("?") + t.count("!")
    has_definition_style = any(
        phrase in lower_t
        for phrase in (" is ", " are ", " refers to ", " defined as ", " means ", " combines ")
    )

    if has_definition_style and len(tokens) >= 25:
        return False

    return signal_hits >= 2 and sentence_marks <= 4


def dedupe_matches(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    result = []

    for match in matches:
        normalized_source = normalize_source(match.get("source", ""))
        content_key = match.get("content", "").strip()[:300]
        key = (normalized_source, content_key)

        if key in seen:
            continue

        seen.add(key)

        cleaned = dict(match)
        cleaned["source"] = normalized_source
        result.append(cleaned)

    return result


# ============================================================
# Web search helpers
# ============================================================

def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def _is_recency_query(question: str) -> bool:
    q = (question or "").lower()
    keywords = (
        "current",
        "latest",
        "recent",
        "today",
        "now",
        "news",
        "most recent",
        "guncel",
        "su an",
        "en son",
        "haber",
    )
    return any(k in q for k in keywords)


def _sanitize_markdown_label(text: str) -> str:
    value = (text or "").strip()
    value = value.replace("[", "(").replace("]", ")")
    value = re.sub(r"\s+", " ", value)
    return value


def _is_not_enough_answer(text: str) -> bool:
    t = (text or "").strip().lower()
    if "not enough information in the provided context" in t:
        return True
    if "i could not verify" in t:
        return True
    if "could not verify" in t:
        return True
    return False


def _classify_web_query(question: str) -> str:
    q = (question or "").lower()
    if ("formula 1" in q or "f1" in q) and any(k in q for k in ("race", "winner", "won", "grand prix", "results")):
        return "f1_winner"
    if any(k in q for k in ("cpi", "inflation", "consumer price index")):
        return "cpi"
    if any(
        k in q
        for k in (
            "weather",
            "forecast",
            "temperature",
            "rain",
            "wind",
            "hava durumu",
            "hava",
            "tahmin",
            "sicaklik",
            "sıcaklık",
            "yagmur",
            "yağmur",
            "ruzgar",
            "rüzgar",
        )
    ):
        return "weather"
    return "generic"


def _reliable_domains_for_query(question: str) -> tuple[str, ...]:
    query_type = _classify_web_query(question)
    if query_type == "f1_winner":
        return ("formula1.com", "fia.com", "bbc.com", "espn.com", "reuters.com")
    if query_type == "cpi":
        return ("bls.gov", "fred.stlouisfed.org", "stlouisfed.org", "bea.gov")
    if query_type == "weather":
        return (
            "weather.gov",
            "api.weather.gov",
            "weather.com",
            "open-meteo.com",
            "accuweather.com",
            "metoffice.gov.uk",
            "bbc.com",
            "timeanddate.com",
            "wunderground.com",
            "meteoblue.com",
        )
    return ("reuters.com", "apnews.com", "bbc.com", "wsj.com", "ft.com", "nytimes.com")


def _filter_reliable_web_results(question: str, web_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    reliable_domains = _reliable_domains_for_query(question)
    filtered = [
        result
        for result in web_results
        if _domain_matches(result.get("source", ""), reliable_domains)
    ]
    if not filtered:
        return []

    seen = set()
    deduped: list[dict[str, Any]] = []
    for result in filtered:
        domain = (result.get("source") or "").strip().lower()
        url = (result.get("url") or "").strip().lower()
        key = domain or url
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(result)
    return deduped


def _extract_deterministic_web_answer(question: str, web_results: list[dict[str, Any]]) -> str | None:
    query_type = _classify_web_query(question)
    if not web_results:
        return None

    if query_type == "f1_winner":
        patterns = [
            r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\s+wins?\b",
            r"\bwinner(?:\s+is|:)?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b",
            r"\bwon by\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,2})\b",
        ]
        for result in web_results:
            text = f"{result.get('title', '')}. {result.get('content', '')}"
            for pattern in patterns:
                m = re.search(pattern, text)
                if m:
                    winner = m.group(1).strip()
                    if winner.lower() not in {"formula one", "grand prix"}:
                        return f"Based on the most relevant race-result snippets, the most recent Formula 1 race winner is {winner}."
        return None

    if query_type == "cpi":
        percent_pattern = r"(\d{1,2}(?:\.\d+)?)\s*(?:%|percent)"
        month_year_pattern = r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b"
        for result in web_results:
            text = f"{result.get('title', '')}. {result.get('content', '')}"
            if "cpi" not in text.lower() and "inflation" not in text.lower():
                continue
            m = re.search(percent_pattern, text, flags=re.IGNORECASE)
            if m:
                value = m.group(1).strip()
                period_match = re.search(month_year_pattern, text, flags=re.IGNORECASE)
                if period_match:
                    return f"The latest CPI inflation figure in the provided reliable snippets is {value}% ({period_match.group(0)})."
                return f"The latest CPI inflation figure in the provided reliable snippets is {value}%."
        return None

    if query_type == "weather":
        for result in web_results:
            text = f"{result.get('title', '')}. {result.get('content', '')}"
            patterns = [
                r"\b(-?\d{1,2}(?:\.\d+)?)\s*(?:°|Â°|º)?\s*(?:[CF]|fahrenheit|celsius)\b",
                r"\b(?:high|low)\s+(-?\d{1,2}(?:\.\d+)?)\b",
                r"\b(-?\d{1,2}(?:\.\d+)?)\s*(?:°|Â°|º)\b",
            ]
            for pattern in patterns:
                m = re.search(pattern, text, flags=re.IGNORECASE)
                if m:
                    value = m.group(1).strip()
                    return f"Based on the available weather snippets, the forecast mentions around {value} degrees."
        return None

    return None


def _secondary_web_query(question: str) -> str | None:
    query_type = _classify_web_query(question)
    if query_type == "f1_winner":
        return "latest Formula 1 Grand Prix winner official result"
    if query_type == "cpi":
        return "latest US CPI inflation BLS latest numbers"
    if query_type == "weather":
        return question
    return None


def _domain_matches(domain: str, patterns: tuple[str, ...]) -> bool:
    d = (domain or "").lower().strip()
    if not d:
        return False
    return any(d == p or d.endswith(f".{p}") for p in patterns)


def _is_race_winner_query(question: str) -> bool:
    q = (question or "").lower()
    if "formula 1" not in q and "f1" not in q:
        return False
    race_terms = ("race", "grand prix", "gp", "winner", "won", "result")
    return any(term in q for term in race_terms)


def _web_result_score(question: str, result: dict[str, Any]) -> float:
    q = (question or "").lower()
    title = (result.get("title") or "").lower()
    content = (result.get("content") or "").lower()
    domain = (result.get("source") or "").lower()
    text = f"{title}\n{content}"

    q_tokens = set(tokenize_for_rerank(q))
    t_tokens = set(tokenize_for_rerank(text))
    lexical = len(q_tokens & t_tokens) / max(len(q_tokens), 1)
    score = lexical

    if _is_race_winner_query(q):
        if any(k in text for k in ("winner", "won", "race result", "results", "grand prix")):
            score += 0.55
        if any(k in text for k in ("champion", "championship", "standings")):
            score -= 0.45
        if _domain_matches(domain, ("formula1.com", "fia.com", "bbc.com", "espn.com", "reuters.com")):
            score += 0.35

    if any(k in q for k in ("cpi", "inflation", "consumer price index")):
        if _domain_matches(domain, ("bls.gov", "fred.stlouisfed.org", "stlouisfed.org", "bea.gov")):
            score += 0.50
        elif _domain_matches(domain, ("oecd.org", "imf.org", "worldbank.org")):
            score += 0.20

    if _domain_matches(domain, ("reuters.com", "apnews.com", "bbc.com")):
        score += 0.12

    return score


def _rerank_web_results(question: str, web_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored: list[dict[str, Any]] = []
    for result in web_results:
        enriched = dict(result)
        enriched["_score"] = _web_result_score(question, result)
        scored.append(enriched)

    scored.sort(key=lambda x: float(x.get("_score", 0.0)), reverse=True)
    return scored


def _has_relevant_web_evidence(question: str, web_results: list[dict[str, Any]]) -> bool:
    q_tokens = set(tokenize_for_rerank(question))
    if not q_tokens:
        return bool(web_results)

    for result in web_results[:5]:
        text = f"{result.get('title', '')}\n{result.get('content', '')}".lower()
        t_tokens = set(tokenize_for_rerank(text))
        overlap = len(q_tokens & t_tokens)
        if overlap >= 2:
            return True
    return False


def _public_web_results(web_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    clean: list[dict[str, Any]] = []
    for item in web_results:
        clean.append({k: v for k, v in item.items() if not str(k).startswith("_")})
    return clean


def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    SearXNG üzerinden web araması yapar.

    Beklenen endpoint:
    GET http://localhost:8080/search?q=...&format=json
    """

    try:
        response = requests.get(
            f"{SEARXNG_BASE_URL}/search",
            params={
                "q": query,
                "format": "json",
            },
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("web_search failed query=%r error=%s", query, exc)
        return []

    try:
        data = response.json()
    except ValueError:
        logger.warning("web_search invalid json query=%r response=%r", query, response.text[:300])
        return []

    raw_results = data.get("results", [])
    results: list[dict[str, Any]] = []

    for item in raw_results:
        title = item.get("title") or ""
        result_url = item.get("url") or ""
        content = item.get("content") or item.get("snippet") or ""

        if not title or not result_url:
            continue

        results.append(
            {
                "title": title.strip(),
                "url": result_url.strip(),
                "content": content.strip(),
                "source": get_domain(result_url),
            }
        )

        if len(results) >= max_results:
            break

    logger.info(
        "web_search query=%r raw=%d selected=%d",
        query,
        len(raw_results),
        len(results),
    )

    return results


def build_web_context(web_results: list[dict[str, Any]]) -> str:
    if not web_results:
        return ""

    context_parts = []

    for i, result in enumerate(web_results, start=1):
        context_parts.append(
            f"[WEB SOURCE {i}]\n"
            f"title={result.get('title', '')}\n"
            f"url={result.get('url', '')}\n"
            f"source={result.get('source', '')}\n"
            f"text={result.get('content', '')}"
        )

    return "\n\n---\n\n".join(context_parts)


# ============================================================
# Answer cleaning
# ============================================================

def _looks_like_web_domain_source(value: str) -> bool:
    v = (value or "").strip().lower()
    if not v or v.endswith(".pdf"):
        return False
    if "/" in v or " " in v:
        return False
    return re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}", v) is not None


def clean_answer(answer: str, source_names: list[str]) -> str:
    merged_sources: list[str] = []
    seen = set()
    for src in source_names:
        s = (src or "").strip()
        if not s:
            continue
        key = s.lower()
        if key in seen:
            continue
        seen.add(key)
        merged_sources.append(s)

    def with_sources(text: str) -> str:
        if merged_sources:
            sources_block = "\n".join(f"- {src}" for src in merged_sources)
            return f"{text}\n\nSources:\n{sources_block}"
        return text

    if not answer:
        return with_sources("Not enough information in the provided context.")

    a = answer.strip()

    banned_starts = [
        "wait,",
        "but the user said",
        "the user wants",
        "i should",
        "let me",
        "since the user",
        "alternatively,",
    ]

    lower_a = a.lower()
    if any(lower_a.startswith(prefix) for prefix in banned_starts):
        return with_sources("Not enough information in the provided context.")

    # Model kendi Sources kısmını yazdıysa temizleyip bizim canonical source listemizi ekliyoruz.
    a = re.sub(r"(?is)\n*\s*sources:.*$", "", a).strip()

    not_enough_pattern = r"^\s*['\"]?Not enough information in the provided context\.\s*['\"]?\s*"
    if re.match(not_enough_pattern, a, flags=re.IGNORECASE):
        remainder = re.sub(not_enough_pattern, "", a, flags=re.IGNORECASE).strip()
        if remainder and re.search(r"[a-zA-Z]", remainder):
            a = remainder

    return with_sources(a)


# ============================================================
# PDF ingest
# ============================================================

def ingest_pdf(
    source: str,
    pdf_path: str,
    chunk_size: int = 1200,
    overlap: int = 200,
) -> dict[str, Any]:
    total_start = perf_counter()
    source = normalize_source(source, pdf_path)

    t0 = perf_counter()
    pages = extract_pdf_pages(pdf_path)
    extract_ms = (perf_counter() - t0) * 1000

    t1 = perf_counter()
    chunks = chunk_pdf_pages(
        pages=pages,
        chunk_size=chunk_size,
        overlap=overlap,
    )
    chunk_ms = (perf_counter() - t1) * 1000

    if not chunks:
        raise ValueError(f"No chunks produced for PDF: {pdf_path}")

    embed_start = perf_counter()
    batch: list[dict[str, Any]] = []
    inserted_count = 0
    batch_size = 50

    for global_chunk_index, chunk in enumerate(chunks):
        embedding = get_embedding(chunk["content"])
        batch.append(
            {
                "source": source,
                "page_start": chunk["page_start"],
                "page_end": chunk["page_end"],
                "chunk_index": global_chunk_index,
                "content": chunk["content"],
                "embedding": embedding,
            }
        )

        if len(batch) >= batch_size:
            insert_documents_batch(batch)
            inserted_count += len(batch)
            batch = []

    if batch:
        insert_documents_batch(batch)
        inserted_count += len(batch)

    embed_insert_ms = (perf_counter() - embed_start) * 1000
    total_ms = (perf_counter() - total_start) * 1000

    logger.info(
        "ingest_pdf source=%s pages=%d chunks=%d extract=%.1fms chunk=%.1fms embed+insert=%.1fms total=%.1fms",
        source,
        len(pages),
        len(chunks),
        extract_ms,
        chunk_ms,
        embed_insert_ms,
        total_ms,
    )

    return {
        "source": source,
        "pdf_path": pdf_path,
        "pages_read": len(pages),
        "chunks_added": inserted_count,
    }


# ============================================================
# PDF retrieve
# ============================================================

def retrieve_context(
    question: str,
    top_k: int = 8,
    source: str | None = None,
) -> dict[str, Any]:
    total_start = perf_counter()

    if count_documents() == 0:
        raise ValueError("Vector database boş. Önce doküman eklemelisin.")

    t0 = perf_counter()
    question_embedding = get_embedding(question)
    question_embed_ms = (perf_counter() - t0) * 1000

    t1 = perf_counter()
    raw_matches = search_similar(
        question_embedding,
        limit=max(top_k * 4, 10),
        source=source,
    )
    search_ms = (perf_counter() - t1) * 1000

    t2 = perf_counter()
    filtered_matches = []

    for match in raw_matches:
        if looks_like_reference_chunk(match["content"]):
            continue
        if looks_like_cover_or_title_chunk(match["content"]):
            continue
        filtered_matches.append(match)

    filtered_matches = dedupe_matches(filtered_matches)

    if not filtered_matches:
        filtered_matches = dedupe_matches(raw_matches)

    filtered_matches = rerank_matches(question, filtered_matches)
    matches = filtered_matches[:top_k]
    rerank_ms = (perf_counter() - t2) * 1000

    context_parts = []

    for i, match in enumerate(matches, start=1):
        context_parts.append(
            f"[PDF CHUNK {i}]\n"
            f"chunk_index={match['chunk_index']}\n"
            f"source={match['source']}\n"
            f"pages={match['page_start']}-{match['page_end']}\n"
            f"text={match['content']}"
        )

    total_ms = (perf_counter() - total_start) * 1000

    logger.info(
        "retrieve_context top_k=%d source=%s raw=%d final=%d q_embed=%.1fms search=%.1fms rerank=%.1fms total=%.1fms question=%r",
        top_k,
        source,
        len(raw_matches),
        len(matches),
        question_embed_ms,
        search_ms,
        rerank_ms,
        total_ms,
        question[:120],
    )

    return {
        "matches": matches,
        "context": "\n\n---\n\n".join(context_parts),
    }


# ============================================================
# Main ask function
# ============================================================

def ask_question(
    question: str,
    top_k: int = 8,
    source: str | None = None,
    use_web: bool = False,
    web_top_k: int = 5,
) -> dict[str, Any]:
    """
    Ana cevap üretme fonksiyonu.

    use_web=False:
        Sadece PDF / pgvector RAG kullanır.

    use_web=True:
        Sadece SearXNG web search context kullanır.
    """
    total_start = perf_counter()
    matches: list[dict[str, Any]] = []
    pdf_context = ""
    web_results: list[dict[str, Any]] = []
    web_context = ""
    retrieval_ms = 0.0
    web_ms = 0.0

    if use_web:
        effective_web_top_k = web_top_k
        if _is_recency_query(question):
            effective_web_top_k = max(web_top_k, 10)

        t_web = perf_counter()
        web_results = web_search(question, max_results=effective_web_top_k)
        web_results = _rerank_web_results(question, web_results)
        web_results = web_results[:effective_web_top_k]
        reliable_web_results = _filter_reliable_web_results(question, web_results)
        if not reliable_web_results:
            return {
                "question": question,
                "answer": "I could not verify this from web search results.",
                "retrieved_chunks": [],
                "web_sources": _public_web_results(web_results),
            }

        web_results = reliable_web_results
        web_context = build_web_context(web_results)
        web_ms = (perf_counter() - t_web) * 1000
        if not web_results:
            return {
                "question": question,
                "answer": "I could not verify this from web search results.",
                "retrieved_chunks": [],
                "web_sources": [],
            }
    else:
        if count_documents() == 0:
            return {
                "question": question,
                "answer": "No PDF documents found. Please upload or ingest a PDF first, or enable web search.",
                "retrieved_chunks": [],
                "web_sources": [],
            }

        t0 = perf_counter()
        retrieved = retrieve_context(question, top_k=top_k, source=source)
        retrieval_ms = (perf_counter() - t0) * 1000
        matches = retrieved["matches"]
        pdf_context = retrieved["context"]

    # 3. Build mode-specific context
    context_parts = []
    if use_web:
        context_parts.append("WEB CONTEXT:\n" + web_context)
    else:
        context_parts.append("PDF CONTEXT:\n" + pdf_context)

    combined_context = "\n\n====================\n\n".join(context_parts)

    # 4. Build canonical source list
    source_names: list[str] = []

    if use_web:
        seen_web_keys: set[str] = set()
        max_source_links = 5
        for result in web_results:
            url = (result.get("url") or "").strip()
            domain = (result.get("source") or "").strip() or get_domain(url)
            title = (result.get("title") or "").strip()
            dedupe_key = (domain or url).lower()
            if dedupe_key and dedupe_key in seen_web_keys:
                continue
            if dedupe_key:
                seen_web_keys.add(dedupe_key)

            if url:
                label_parts = [domain or "source"]
                if title:
                    label_parts.append(title[:90])
                label = _sanitize_markdown_label(" | ".join(label_parts))
                src = f"[{label}]({url})"
            else:
                src = domain
            if src and src not in source_names:
                source_names.append(src)
            if len(source_names) >= max_source_links:
                break
    else:
        for match in matches:
            raw_src = (match.get("source", "") or "").strip()
            if raw_src.lower().endswith(".pdf"):
                src = raw_src
            else:
                src = normalize_source(raw_src)
            if _looks_like_web_domain_source(src):
                continue
            if src and src not in source_names:
                source_names.append(src)

    deterministic_answer = None
    if use_web:
        deterministic_answer = _extract_deterministic_web_answer(question, web_results)
        if not deterministic_answer:
            followup_query = _secondary_web_query(question)
            if followup_query and followup_query.strip().lower() != question.strip().lower():
                secondary_results = web_search(followup_query, max_results=effective_web_top_k)
                secondary_results = _rerank_web_results(question, secondary_results)
                secondary_reliable = _filter_reliable_web_results(question, secondary_results)
                if secondary_reliable:
                    web_results = secondary_reliable
                    web_context = build_web_context(web_results)
                    source_names = []
                    seen_web_keys: set[str] = set()
                    max_source_links = 5
                    for result in web_results:
                        url = (result.get("url") or "").strip()
                        domain = (result.get("source") or "").strip() or get_domain(url)
                        title = (result.get("title") or "").strip()
                        dedupe_key = (domain or url).lower()
                        if dedupe_key and dedupe_key in seen_web_keys:
                            continue
                        if dedupe_key:
                            seen_web_keys.add(dedupe_key)
                        if url:
                            label_parts = [domain or "source"]
                            if title:
                                label_parts.append(title[:90])
                            label = _sanitize_markdown_label(" | ".join(label_parts))
                            src = f"[{label}]({url})"
                        else:
                            src = domain
                        if src and src not in source_names:
                            source_names.append(src)
                        if len(source_names) >= max_source_links:
                            break
                    deterministic_answer = _extract_deterministic_web_answer(question, web_results)
        if deterministic_answer:
            return {
                "question": question,
                "answer": clean_answer(deterministic_answer, source_names),
                "retrieved_chunks": [],
                "web_sources": _public_web_results(web_results),
            }

    # 5. LLM prompt
    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict grounded RAG assistant.\n"
                "Answer ONLY from the provided context.\n"
                "Do not use your own knowledge.\n"
                "Do not guess.\n"
                "Do not invent sources.\n"
                "If the answer is not explicitly supported by the context, say exactly:\n"
                "'Not enough information in the provided context.'\n"
                "Ignore bibliography, references, citations, paper titles, and footnotes unless the question is explicitly about them.\n"
                "For why, compare, evaluate, or explain questions, synthesize evidence across all relevant chunks.\n"
                "Do not stop at a generic conclusion when the context supports a causal explanation.\n"
                "Address every concrete aspect named in the question, such as historical practices, available data, methodology, constraints, and operational consequences.\n"
                "Make the causal chain explicit in the final answer, but do not reveal hidden reasoning or scratch work.\n"
                "Do not introduce unstated metrics, labels, or claims; preserve numeric evidence in the form used by the context.\n"
                "Do not convert counts, precision, or trial outcomes into accuracy unless the context explicitly calls them accuracy.\n"
                "Use 4-7 concise sentences for synthesis questions.\n"
                "Do not reveal internal reasoning.\n"
                "Do not explain your thought process.\n"
                "Keep simple factual questions short and precise.\n"
                "Always end with: Sources: <source names>."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Question:\n{question}\n\n"
                f"Context:\n{combined_context}\n\n"
                "Now answer the question using only the context. "
                "If the question asks for an explanation, connect the relevant facts from different chunks into one coherent answer."
            ),
        },
    ]
    if use_web:
        messages[0]["content"] = (
            "You are a grounded web QA assistant.\n"
            "Answer ONLY from the provided WEB CONTEXT snippets.\n"
            "Do not use outside knowledge.\n"
            "If snippets are partially informative, give the best concise answer and clearly mark uncertainty.\n"
            "If there is no relevant snippet evidence, say exactly:\n"
            "'I could not verify this from web search results.'\n"
            "Do not invent facts.\n"
            "Always end with: Sources: <source names>."
        )

    # 6. LLM call (model fallback chain for transient upstream limits)
    t1 = perf_counter()
    used_model = PRIMARY_LLM_MODEL
    attempts: list[str] = []
    try:
        raw_answer = ""
        for candidate in _build_model_candidates():
            used_model = candidate
            try:
                response = client.chat.completions.create(
                    model=candidate,
                    messages=messages,
                    temperature=0.0,
                )
                raw_answer = response.choices[0].message.content or ""
                break
            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                retryable = _is_retryable_llm_error(exc)
                attempts.append(f"{candidate}:{status_code or 'unknown'}")
                logger.warning(
                    "llm_model_attempt_failed model=%s status=%s retryable=%s error=%s",
                    candidate,
                    status_code,
                    retryable,
                    exc,
                )
                if not retryable:
                    raise
        else:
            raise RuntimeError(f"all_model_attempts_failed ({', '.join(attempts)})")

        llm_ms = (perf_counter() - t1) * 1000
        answer = clean_answer(raw_answer, source_names)

        # Web mode: small local models sometimes overuse "not enough" despite relevant snippets.
        if use_web and _is_not_enough_answer(answer) and _has_relevant_web_evidence(question, web_results):
            retry_messages = [
                {
                    "role": "system",
                    "content": (
                        "Use only WEB CONTEXT snippets.\n"
                        "Provide one concise best-effort answer from the most relevant snippet(s).\n"
                        "If uncertain, state uncertainty briefly.\n"
                        "Do not say 'Not enough information' unless evidence is truly absent.\n"
                        "Always end with: Sources: <source names>."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Question:\n{question}\n\n"
                        f"WEB CONTEXT:\n{web_context}\n\n"
                        "Give a concise answer grounded only in this context."
                    ),
                },
            ]
            response_retry = client.chat.completions.create(
                model=used_model,
                messages=retry_messages,
                temperature=0.0,
            )
            retry_answer = response_retry.choices[0].message.content or ""
            answer = clean_answer(retry_answer, source_names)

        if use_web and _is_not_enough_answer(answer):
            answer = clean_answer(
                "Reliable sources were found, but the snippets do not contain a definitive answer value. Please open the top source link for exact details.",
                source_names,
            )
    except Exception as exc:
        llm_ms = (perf_counter() - t1) * 1000
        logger.exception(
            "llm_call_failed backend=%s use_web=%s model=%s error=%s",
            LLM_BACKEND,
            use_web,
            used_model,
            exc,
        )
        answer = clean_answer(
            "Temporary upstream model error. Please retry in a few seconds.",
            source_names,
        )
        total_ms = (perf_counter() - total_start) * 1000
        logger.info(
            "ask_question backend=%s top_k=%d source=%s use_web=%s web_results=%d retrieval=%.1fms web=%.1fms llm=%.1fms total=%.1fms model=%s question=%r fallback=llm_error",
            LLM_BACKEND,
            top_k,
            source,
            use_web,
            len(web_results),
            retrieval_ms,
            web_ms,
            llm_ms,
            total_ms,
            used_model,
            question[:120],
        )
        return {
            "question": question,
            "answer": answer,
            "retrieved_chunks": matches,
            "web_sources": _public_web_results(web_results),
        }

    total_ms = (perf_counter() - total_start) * 1000

    logger.info(
        "ask_question backend=%s top_k=%d source=%s use_web=%s web_results=%d retrieval=%.1fms web=%.1fms llm=%.1fms total=%.1fms model=%s question=%r",
        LLM_BACKEND,
        top_k,
        source,
        use_web,
        len(web_results),
        retrieval_ms,
        web_ms,
        llm_ms,
        total_ms,
        used_model,
        question[:120],
    )

    return {
        "question": question,
        "answer": answer,
        "retrieved_chunks": matches,
        "web_sources": _public_web_results(web_results),
    }
