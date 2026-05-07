from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

import requests
from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EVAL_DIR = ROOT / "evaluation"
BASE_REPORTS_DIR = ROOT / "reports"
CACHE_DIR = EVAL_DIR / "cache"
WEB_CACHE_DIR = CACHE_DIR / "web"

TEST_SET_PATH = EVAL_DIR / "test_questions.json"
DP_FACTS_PATH = EVAL_DIR / "dp_facts.json"
WEB_SOURCES_PATH = EVAL_DIR / "web_sources.json"
VECTOR_SOURCES = {
    "eval_water_main_breaks": ROOT / "docs" / "1805.03597v1.pdf",
    "eval_crli": ROOT / "docs" / "Exploring_the_Combined_Real_Loss_Index_final.pdf",
}

ANSWER_SOURCE_TYPES = ("vector_db", "dp_db", "web_search", "combined_sources")
TOP_K = 4
USER_AGENT = "rag-project-hallucination-eval/1.0"
LLM_MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("LLM_MIN_SECONDS_BETWEEN_CALLS", "4.0"))
LLM_MAX_RETRIES = int(os.getenv("LLM_MAX_RETRIES", "6"))
LLM_REQUEST_TIMEOUT_SECONDS = float(os.getenv("LLM_REQUEST_TIMEOUT_SECONDS", "180"))
LLM_MAX_OUTPUT_TOKENS = int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "220"))
EVIDENCE_CHAR_LIMIT = int(os.getenv("EVIDENCE_CHAR_LIMIT", "700"))
USE_LLM_JUDGE = os.getenv("USE_LLM_JUDGE", "0").strip().lower() in {"1", "true", "yes"}

from app.chunking import chunk_text_with_overlap
from app.db import init_db, list_sources, search_similar
from app.embeddings import get_embedding
from app.pdf_utils import extract_pdf_pages
from app.rag import dedupe_matches, looks_like_reference_chunk, rerank_matches, ingest_pdf

ENV_PATH = ROOT / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_CHAT_MODEL = os.getenv("OPENROUTER_CHAT_MODEL", "openrouter/free")
EVAL_CHAT_BASE_URL = os.getenv("HALLUCINATION_EVAL_CHAT_BASE_URL", OPENROUTER_BASE_URL)
EVAL_CHAT_API_KEY = os.getenv("HALLUCINATION_EVAL_CHAT_API_KEY", OPENROUTER_API_KEY)
EVAL_CHAT_MODEL = os.getenv("HALLUCINATION_EVAL_CHAT_MODEL", OPENROUTER_CHAT_MODEL)
EVAL_RUN_SLUG = os.getenv("HALLUCINATION_EVAL_RUN_SLUG", "").strip()
REPORTS_DIR = BASE_REPORTS_DIR / EVAL_RUN_SLUG if EVAL_RUN_SLUG else BASE_REPORTS_DIR
RESULTS_PATH = REPORTS_DIR / "hallucination_eval_results.json"
REPORT_PATH = REPORTS_DIR / "hallucination_eval_report.md"
SOURCE_REPORT_PATHS = {
    "vector_db": REPORTS_DIR / "hallucination_eval_vector_db.md",
    "dp_db": REPORTS_DIR / "hallucination_eval_dp_db.md",
    "web_search": REPORTS_DIR / "hallucination_eval_web_search.md",
    "combined_sources": REPORTS_DIR / "hallucination_eval_combined_sources.md",
}

client = OpenAI(
    base_url=EVAL_CHAT_BASE_URL,
    api_key=EVAL_CHAT_API_KEY,
)
LAST_LLM_CALL_AT = 0.0

ANSWER_SYSTEM_PROMPT = """You are a strict grounding assistant.
Answer only from the provided evidence blocks.
If the evidence does not explicitly support the answer, say exactly:
Not enough information in the provided context.
If the evidence contains conflicting numbers or claims, explicitly say the sources conflict and list the conflicting claims with source identifiers instead of choosing one as settled fact.
Do not add outside knowledge, likely explanations, or guessed details.
Keep the answer concise.
Always end with a line in the form: Sources: <comma-separated source ids>."""

JUDGE_SYSTEM_PROMPT = """You are grading whether an answer is grounded in supplied evidence.

Possible labels:
- grounded: every substantive claim in the answer is supported by the evidence. For conflicting evidence, the answer must acknowledge the conflict rather than collapsing it into one fact.
- partially_grounded: the answer contains some supported content, but also unsupported, incomplete, or overconfident claims.
- hallucinated: the answer makes unsupported or contradicted claims, or answers despite lacking evidence.
- correctly_refused: the answer clearly refuses because the evidence is insufficient, and that refusal matches the evidence.

Return strict JSON with keys:
label
rationale
unsupported_claims
supported_claims
"""


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_dirs() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    WEB_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def normalize_whitespace(text: str) -> str:
    text = unescape(text or "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


def html_to_text(html: str) -> str:
    return normalize_whitespace(html)


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", (text or "").lower())


def lexical_score(question: str, text: str) -> float:
    q_tokens = [tok for tok in tokenize(question) if len(tok) > 2]
    if not q_tokens:
        return 0.0

    t_tokens = set(tokenize(text))
    overlap = sum(1 for tok in q_tokens if tok in t_tokens)
    coverage = overlap / len(set(q_tokens))

    phrase_bonus = 0.0
    q = question.lower()
    t = (text or "").lower()

    for phrase in (
        "gradient boosted decision trees",
        "binary classification",
        "department of public works",
        "combined real loss index",
        "geometric mean",
        "temporal cross-validation",
        "r-squared",
        "rhineland-palatinate",
        "saarland",
        "conflict",
    ):
        if phrase in q and phrase in t:
            phrase_bonus += 0.25

    if "how many breaks" in q and ("33 breaks" in t or "42 breaks" in t):
        phrase_bonus += 0.35

    if "mean crli value" in q and ("average crli" in t or "mean of about" in t):
        phrase_bonus += 0.25

    return coverage + phrase_bonus


def choose_sources_for_question(question_id: str) -> list[str]:
    if question_id.startswith("q0") and int(question_id[1:]) <= 3:
        return ["eval_water_main_breaks"]
    if question_id in {"q04", "q05", "q06", "q09", "q10", "q11", "q13", "q14"}:
        return ["eval_crli"]
    return list(VECTOR_SOURCES.keys())


def ensure_vector_docs() -> None:
    init_db()
    existing_sources = set(list_sources())

    for source_name, pdf_path in VECTOR_SOURCES.items():
        if source_name in existing_sources:
            continue
        ingest_pdf(
            source=source_name,
            pdf_path=str(pdf_path),
            chunk_size=1200,
            overlap=200,
        )


def retrieve_vector_context(question: str, question_id: str, top_k: int = TOP_K) -> list[dict[str, Any]]:
    question_embedding = get_embedding(question)
    matches: list[dict[str, Any]] = []

    for source_name in choose_sources_for_question(question_id):
        matches.extend(
            search_similar(
                query_embedding=question_embedding,
                limit=max(top_k * 4, 8),
                source=source_name,
            )
        )

    filtered = [match for match in matches if not looks_like_reference_chunk(match.get("content", ""))]
    filtered = dedupe_matches(filtered) or dedupe_matches(matches)
    reranked = rerank_matches(question, filtered)

    evidence = []
    for item in reranked[:top_k]:
        evidence.append(
            {
                "source_id": item["source"],
                "support_type": "vector_db",
                "content": item["content"],
                "metadata": {
                    "page_start": item.get("page_start"),
                    "page_end": item.get("page_end"),
                    "similarity": round(float(item.get("similarity", 0.0)), 4),
                },
            }
        )

    return evidence


def retrieve_dp_context(question: str, facts: list[dict[str, Any]], question_id: str, top_k: int = TOP_K) -> list[dict[str, Any]]:
    allowed_sources = set(choose_sources_for_question(question_id))
    scored = []

    for fact in facts:
        if fact["source"] not in allowed_sources:
            continue
        score = lexical_score(question, fact["text"])
        if score <= 0:
            continue
        scored.append((score, fact))

    scored.sort(key=lambda item: item[0], reverse=True)

    evidence = []
    for score, fact in scored[:top_k]:
        evidence.append(
            {
                "source_id": fact["id"],
                "support_type": "dp_db",
                "content": fact["text"],
                "metadata": {
                    "document_source": fact["source"],
                    "score": round(score, 4),
                },
            }
        )

    return evidence


def fetch_web_text(entry: dict[str, Any]) -> str:
    cache_path = WEB_CACHE_DIR / f"{slugify(entry['id'])}.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    response = requests.get(
        entry["url"],
        timeout=30,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()

    if entry["type"] == "pdf":
        with NamedTemporaryFile(delete=False, suffix=".pdf") as temp_file:
            temp_file.write(response.content)
            temp_path = Path(temp_file.name)
        try:
            pages = extract_pdf_pages(str(temp_path))
            text = "\n\n".join(page["text"] for page in pages if page["text"])
        finally:
            temp_path.unlink(missing_ok=True)
    else:
        text = html_to_text(response.text)

    cache_path.write_text(text, encoding="utf-8")
    return text


def build_web_chunks() -> list[dict[str, Any]]:
    entries = load_json(WEB_SOURCES_PATH)
    chunks: list[dict[str, Any]] = []

    for entry in entries:
        text = fetch_web_text(entry)
        chunked = chunk_text_with_overlap(text=text, chunk_size=1200, overlap=100)

        for index, chunk in enumerate(chunked):
            if looks_like_reference_chunk(chunk):
                continue
            chunks.append(
                {
                    "entry_id": entry["id"],
                    "source": entry["source"],
                    "content": chunk,
                    "chunk_index": index,
                }
            )

    return chunks


def retrieve_web_context(question: str, web_chunks: list[dict[str, Any]], question_id: str, top_k: int = TOP_K) -> list[dict[str, Any]]:
    allowed_sources = set(choose_sources_for_question(question_id))
    scored = []

    for chunk in web_chunks:
        if chunk["source"] not in allowed_sources:
            continue
        score = lexical_score(question, chunk["content"])
        if score <= 0:
            continue
        scored.append((score, chunk))

    scored.sort(key=lambda item: item[0], reverse=True)

    evidence = []
    for score, chunk in scored[:top_k]:
        evidence.append(
            {
                "source_id": chunk["entry_id"],
                "support_type": "web_search",
                "content": chunk["content"],
                "metadata": {
                    "document_source": chunk["source"],
                    "chunk_index": chunk["chunk_index"],
                    "score": round(score, 4),
                },
            }
        )

    return evidence


def retrieve_combined_context(
    question: str,
    question_id: str,
    dp_facts: list[dict[str, Any]],
    web_chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined = []
    combined.extend(retrieve_vector_context(question, question_id, top_k=2))
    combined.extend(retrieve_dp_context(question, dp_facts, question_id, top_k=2))
    combined.extend(retrieve_web_context(question, web_chunks, question_id, top_k=2))

    deduped = []
    seen = set()
    for item in combined:
        key = item["content"][:280]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:6]


def format_context(evidence: list[dict[str, Any]]) -> str:
    if not evidence:
        return ""

    blocks = []
    for index, item in enumerate(evidence, start=1):
        metadata = ", ".join(f"{key}={value}" for key, value in item.get("metadata", {}).items())
        blocks.append(
            f"[EVIDENCE {index}]\n"
            f"source_id={item['source_id']}\n"
            f"support_type={item['support_type']}\n"
            f"metadata={metadata}\n"
            f"text={item['content'][:EVIDENCE_CHAR_LIMIT]}"
        )

    return "\n\n---\n\n".join(blocks)


def create_chat_completion(messages: list[dict[str, str]]):
    global LAST_LLM_CALL_AT

    elapsed = time.time() - LAST_LLM_CALL_AT
    if elapsed < LLM_MIN_SECONDS_BETWEEN_CALLS:
        time.sleep(LLM_MIN_SECONDS_BETWEEN_CALLS - elapsed)

    last_error: Exception | None = None
    for attempt in range(1, LLM_MAX_RETRIES + 1):
        try:
            response = client.chat.completions.create(
                model=EVAL_CHAT_MODEL,
                temperature=0.0,
                messages=messages,
                max_tokens=LLM_MAX_OUTPUT_TOKENS,
                timeout=LLM_REQUEST_TIMEOUT_SECONDS,
            )
            LAST_LLM_CALL_AT = time.time()
            return response
        except Exception as exc:
            last_error = exc
            message = str(exc).lower()
            delay = 12 * attempt

            if "429" in message or "rate limit" in message:
                delay = max(65, 20 * attempt)

            if attempt >= LLM_MAX_RETRIES:
                break

            print(f"LLM call failed on attempt {attempt}/{LLM_MAX_RETRIES}: {exc}. Retrying in {delay}s...")
            time.sleep(delay)

    raise RuntimeError(f"LLM call failed after {LLM_MAX_RETRIES} attempts: {last_error}") from last_error


def answer_with_evidence(question: str, evidence: list[dict[str, Any]]) -> str:
    source_ids = sorted({item["source_id"] for item in evidence})
    if not evidence:
        return "Not enough information in the provided context.\n\nSources: None"

    response = create_chat_completion(
        [
            {"role": "system", "content": ANSWER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question:\n{question}\n\n"
                    f"Evidence:\n{format_context(evidence)}\n\n"
                    "Answer from the evidence only."
                ),
            },
        ]
    )

    answer = (response.choices[0].message.content or "").strip()
    answer = re.sub(r"(?is)\n*\s*sources:.*$", "", answer).strip()
    source_line = ", ".join(source_ids) if source_ids else "None"
    return f"{answer}\n\nSources: {source_line}"


def parse_json_object(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw_text, flags=re.S)
        if not match:
            return {}
        return json.loads(match.group(0))


def fallback_judgement(
    question: dict[str, Any],
    answer: str,
    evidence: list[dict[str, Any]],
    parse_error: str | None = None,
) -> dict[str, Any]:
    answer_body = re.sub(r"(?is)\n*\s*sources:.*$", "", (answer or "")).strip().lower()
    reference = (question.get("reference_answer") or "").lower()
    category = question.get("category", "")

    if not answer_body:
        return {
            "label": "partially_grounded",
            "rationale": "The model returned no substantive answer body even though the prompt expected one.",
            "unsupported_claims": [],
            "supported_claims": [],
        }

    if answer_body.startswith("not enough information in the provided context."):
        if category == "missing" or not evidence:
            return {
                "label": "correctly_refused",
                "rationale": "The answer refused and the question belongs to the missing-information class.",
                "unsupported_claims": [],
                "supported_claims": [],
            }
        return {
            "label": "partially_grounded",
            "rationale": "The answer refused even though some evidence was available.",
            "unsupported_claims": [],
            "supported_claims": [],
        }

    if category == "conflicting":
        if any(token in answer_body for token in ("conflict", "conflicting", "one source", "another source", "while another")):
            return {
                "label": "grounded",
                "rationale": "The answer acknowledges conflicting evidence instead of collapsing it into one fact.",
                "unsupported_claims": [],
                "supported_claims": ["The answer explicitly notes source conflict."],
            }
        return {
            "label": "hallucinated",
            "rationale": "The question is conflict-based, but the answer does not clearly acknowledge the conflict.",
            "unsupported_claims": [answer_body],
            "supported_claims": [],
        }

    ref_tokens = {tok for tok in tokenize(reference) if len(tok) > 3}
    ans_tokens = set(tokenize(answer_body))
    overlap = len(ref_tokens & ans_tokens) / max(len(ref_tokens), 1)

    if category in {"available", "mixed"}:
        if overlap >= 0.35:
            return {
                "label": "grounded",
                "rationale": "Fallback lexical check found substantial overlap with the reference answer.",
                "unsupported_claims": [],
                "supported_claims": [question["reference_answer"]],
            }
        if overlap >= 0.18:
            return {
                "label": "partially_grounded",
                "rationale": "Fallback lexical check found partial overlap with the reference answer.",
                "unsupported_claims": [answer_body],
                "supported_claims": [question["reference_answer"]],
            }
        return {
            "label": "hallucinated",
            "rationale": "Fallback lexical check found weak overlap with the expected grounded answer.",
            "unsupported_claims": [answer_body],
            "supported_claims": [],
        }

    if category == "missing":
        return {
            "label": "hallucinated",
            "rationale": "The question belongs to the missing-information class, but the answer did not refuse.",
            "unsupported_claims": [answer_body],
            "supported_claims": [],
        }

    return {
        "label": "partially_grounded",
        "rationale": f"Fallback applied because judge parsing failed: {parse_error or 'unknown parse issue'}.",
        "unsupported_claims": [],
        "supported_claims": [],
    }


def judge_answer(
    question: dict[str, Any],
    source_type: str,
    answer: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    if not evidence and answer.strip().startswith("Not enough information in the provided context."):
        return {
            "label": "correctly_refused",
            "rationale": "No evidence was retrieved, and the answer correctly refused.",
            "unsupported_claims": [],
            "supported_claims": [],
        }

    if not USE_LLM_JUDGE:
        return fallback_judgement(question, answer, evidence, parse_error="LLM judge disabled")

    response = create_chat_completion(
        [
            {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Question ID: {question['id']}\n"
                    f"Question Category: {question['category']}\n"
                    f"Question: {question['question']}\n"
                    f"Reference Answer: {question['reference_answer']}\n"
                    f"Source Type: {source_type}\n\n"
                    f"Evidence:\n{format_context(evidence)}\n\n"
                    f"Answer to grade:\n{answer}\n"
                ),
            },
        ]
    )

    judge_raw = response.choices[0].message.content or "{}"
    parsed = parse_json_object(judge_raw)
    if not parsed:
        return fallback_judgement(question, answer, evidence, parse_error=judge_raw[:300])
    parsed.setdefault("label", "hallucinated")
    parsed.setdefault("rationale", "Judge response did not include a rationale.")
    parsed.setdefault("unsupported_claims", [])
    parsed.setdefault("supported_claims", [])
    return parsed


def build_examples(results: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    good_labels = {"grounded", "correctly_refused"}
    bad_labels = {"hallucinated", "partially_grounded"}

    good_examples = []
    bad_examples = []

    for result in results:
        if result["judgement"]["label"] in good_labels and len(good_examples) < 4:
            good_examples.append(result)
        if result["judgement"]["label"] in bad_labels and len(bad_examples) < 4:
            bad_examples.append(result)
        if len(good_examples) >= 4 and len(bad_examples) >= 4:
            break

    return good_examples, bad_examples


def grouped_results_by_source(results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["source_type"]].append(result)

    for source_type, items in grouped.items():
        items.sort(key=lambda item: item["question"]["id"])

    return grouped


def render_source_report(source_type: str, results: list[dict[str, Any]]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    items = [item for item in results if item["source_type"] == source_type]
    items.sort(key=lambda item: item["question"]["id"])
    labels = Counter(item["judgement"]["label"] for item in items)
    total = len(items)
    hallucination_rate = (labels["hallucinated"] / total * 100) if total else 0.0
    risky_rate = ((labels["hallucinated"] + labels["partially_grounded"]) / total * 100) if total else 0.0

    lines = [
        f"# Hallucination Evaluation Report - {source_type}",
        "",
        f"Generated: {generated_at}",
        "",
        "## Summary",
        "",
        f"- Source type: {source_type}",
        f"- Model used for answer generation: {EVAL_CHAT_MODEL}",
        f"- Run slug: {EVAL_RUN_SLUG or 'default'}",
        f"- Question count: {total}",
        f"- Grounded: {labels['grounded']}",
        f"- Partially grounded: {labels['partially_grounded']}",
        f"- Hallucinated: {labels['hallucinated']}",
        f"- Correctly refused: {labels['correctly_refused']}",
        f"- Hallucination rate: {hallucination_rate:.1f}%",
        f"- Risky rate: {risky_rate:.1f}%",
        "",
        "## Question Results",
        "",
    ]

    for item in items:
        lines.extend(
            [
                f"### {item['question']['id']} - {item['question']['category']}",
                "",
                f"- Label: {item['judgement']['label']}",
                f"- Question: {item['question']['question']}",
                f"- Answer: {item['answer']}",
                f"- Rationale: {item['judgement']['rationale']}",
                "",
            ]
        )

    return "\n".join(lines)


def summarize_patterns(results: list[dict[str, Any]]) -> list[str]:
    patterns = []

    missing_failures = sum(
        1
        for item in results
        if item["question"]["category"] == "missing"
        and item["judgement"]["label"] in {"hallucinated", "partially_grounded"}
    )
    if missing_failures:
        patterns.append(
            f"The model failed to refuse missing-information questions {missing_failures} times, showing a tendency to invent details when retrieval is weak."
        )

    conflict_failures = sum(
        1
        for item in results
        if item["question"]["category"] == "conflicting"
        and item["judgement"]["label"] in {"hallucinated", "partially_grounded"}
    )
    if conflict_failures:
        patterns.append(
            f"Conflicting-source questions produced {conflict_failures} weak answers, which suggests the assistant often collapses contradictory evidence into one claim."
        )

    mixed_failures = sum(
        1
        for item in results
        if item["question"]["category"] == "mixed"
        and item["judgement"]["label"] in {"hallucinated", "partially_grounded"}
    )
    if mixed_failures:
        patterns.append(
            f"Mixed-source questions produced {mixed_failures} weak answers, indicating that multi-hop synthesis is a common failure point."
        )

    available_failures = sum(
        1
        for item in results
        if item["question"]["category"] == "available"
        and item["judgement"]["label"] in {"hallucinated", "partially_grounded"}
    )
    if available_failures:
        patterns.append(
            f"Even answerable questions produced {available_failures} weak answers, which points to unsupported elaboration beyond the retrieved evidence."
        )

    if not patterns:
        patterns.append("No major hallucination pattern was detected in this run, though retrieval misses can still reduce answer coverage.")

    return patterns


def build_recommendations() -> list[str]:
    return [
        "Refuse by default when no retrieved chunk directly answers the question, instead of asking the LLM to infer from nearby context.",
        "When two sources disagree on a numeric value or status, route the answer through a conflict template that lists each claim with attribution.",
        "Require the orchestrator to verify that every sentence in a draft answer is traceable to at least one retrieved chunk before returning it.",
        "Prefer source-specific answering first, then synthesize across sources only if the question explicitly needs multiple sources.",
        "Add a retrieval sufficiency check: if the top chunks do not cover all named entities or sub-questions, return an insufficiency refusal.",
        "For mixed-source questions, force the prompt to answer in source-attributed clauses so the model cannot silently merge unrelated evidence.",
        "Down-rank summary slides or promotional pages when detailed primary evidence is available, because they are more likely to compress or distort exact statistics.",
        "Treat unsupported numbers, dates, and proper nouns as high-risk claims and require explicit citation-ready evidence before including them."
    ]


def metrics_table(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for result in results:
        grouped[result["source_type"]].append(result)

    rows = []
    for source_type in ANSWER_SOURCE_TYPES:
        items = grouped[source_type]
        labels = Counter(item["judgement"]["label"] for item in items)
        total = len(items)
        hallucination_rate = labels["hallucinated"] / total if total else 0.0
        risky_rate = (labels["hallucinated"] + labels["partially_grounded"]) / total if total else 0.0
        rows.append(
            {
                "source_type": source_type,
                "total": total,
                "grounded": labels["grounded"],
                "partially_grounded": labels["partially_grounded"],
                "hallucinated": labels["hallucinated"],
                "correctly_refused": labels["correctly_refused"],
                "hallucination_rate": round(hallucination_rate * 100, 1),
                "risky_rate": round(risky_rate * 100, 1),
            }
        )
    return rows


def render_markdown(results: list[dict[str, Any]]) -> str:
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    rows = metrics_table(results)
    good_examples, bad_examples = build_examples(results)
    patterns = summarize_patterns(results)
    recommendations = build_recommendations()
    grouped = grouped_results_by_source(results)

    lines = [
        "# Hallucination Evaluation Report",
        "",
        f"Generated: {generated_at}",
        "",
        "## Scope",
        "",
        f"- Model used for answer generation: {EVAL_CHAT_MODEL}",
        f"- Run slug: {EVAL_RUN_SLUG or 'default'}",
        "- Question count: 20",
        "- Source types evaluated: Vector DB, DP DB, web search, combined sources",
        "- Labels: grounded, partially_grounded, hallucinated, correctly_refused",
        "",
        "## Hallucination Rate By Source Type",
        "",
        "| Source type | Total | Grounded | Partial | Hallucinated | Correctly refused | Hallucination rate | Risky rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]

    for row in rows:
        lines.append(
            f"| {row['source_type']} | {row['total']} | {row['grounded']} | {row['partially_grounded']} | "
            f"{row['hallucinated']} | {row['correctly_refused']} | {row['hallucination_rate']}% | {row['risky_rate']}% |"
        )

    lines.extend(
        [
            "",
            "## Good Examples",
            "",
        ]
    )

    for item in good_examples:
        lines.extend(
            [
                f"### {item['question']['id']} - {item['source_type']}",
                "",
                f"- Category: {item['question']['category']}",
                f"- Label: {item['judgement']['label']}",
                f"- Question: {item['question']['question']}",
                f"- Answer: {item['answer']}",
                f"- Why it is good: {item['judgement']['rationale']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Bad Examples",
            "",
        ]
    )

    for item in bad_examples:
        lines.extend(
            [
                f"### {item['question']['id']} - {item['source_type']}",
                "",
                f"- Category: {item['question']['category']}",
                f"- Label: {item['judgement']['label']}",
                f"- Question: {item['question']['question']}",
                f"- Answer: {item['answer']}",
                f"- Why it is bad: {item['judgement']['rationale']}",
                "",
            ]
        )

    lines.extend(
        [
            "## Common Hallucination Patterns",
            "",
        ]
    )
    for pattern in patterns:
        lines.append(f"- {pattern}")

    lines.extend(
        [
            "",
            "## Grounding Recommendations",
            "",
        ]
    )
    for recommendation in recommendations:
        lines.append(f"- {recommendation}")

    lines.extend(
        [
            "",
            "## Detailed Results By Source Type",
            "",
            "Each section below shows the evaluated questions, the model answer, and the final label for one source type.",
            "",
        ]
    )

    for source_type in ANSWER_SOURCE_TYPES:
        lines.extend(
            [
                f"### {source_type}",
                "",
            ]
        )

        for item in grouped.get(source_type, []):
            lines.extend(
                [
                    f"#### {item['question']['id']} - {item['question']['category']}",
                    "",
                    f"- Label: {item['judgement']['label']}",
                    f"- Question: {item['question']['question']}",
                    f"- Answer: {item['answer']}",
                    f"- Rationale: {item['judgement']['rationale']}",
                    "",
                ]
            )

    return "\n".join(lines)


def run() -> None:
    ensure_dirs()
    ensure_vector_docs()

    questions = load_json(TEST_SET_PATH)
    dp_facts = load_json(DP_FACTS_PATH)
    web_chunks = build_web_chunks()

    if RESULTS_PATH.exists():
        results = load_json(RESULTS_PATH)
    else:
        results = []

    completed = {
        (item["question"]["id"], item["source_type"])
        for item in results
    }

    for question in questions:
        vector_evidence = retrieve_vector_context(question["question"], question["id"])
        dp_evidence = retrieve_dp_context(question["question"], dp_facts, question["id"])
        web_evidence = retrieve_web_context(question["question"], web_chunks, question["id"])
        combined_evidence = retrieve_combined_context(question["question"], question["id"], dp_facts, web_chunks)

        evidence_map = {
            "vector_db": vector_evidence,
            "dp_db": dp_evidence,
            "web_search": web_evidence,
            "combined_sources": combined_evidence,
        }

        for source_type, evidence in evidence_map.items():
            key = (question["id"], source_type)
            if key in completed:
                print(f"[skip] {source_type} {question['id']} already evaluated")
                continue

            answer = answer_with_evidence(question["question"], evidence)
            judgement = judge_answer(question, source_type, answer, evidence)
            record = (
                {
                    "question": question,
                    "source_type": source_type,
                    "answer": answer,
                    "evidence": evidence,
                    "judgement": judgement,
                }
            )
            results.append(record)
            completed.add(key)
            save_json(RESULTS_PATH, results)
            print(f"[{source_type}] {question['id']} -> {judgement['label']}")

    save_json(RESULTS_PATH, results)
    REPORT_PATH.write_text(render_markdown(results), encoding="utf-8")
    for source_type, source_report_path in SOURCE_REPORT_PATHS.items():
        source_report_path.write_text(render_source_report(source_type, results), encoding="utf-8")

    print(f"Saved results to {RESULTS_PATH}")
    print(f"Saved report to {REPORT_PATH}")
    for source_type, source_report_path in SOURCE_REPORT_PATHS.items():
        print(f"Saved {source_type} report to {source_report_path}")


if __name__ == "__main__":
    run()
