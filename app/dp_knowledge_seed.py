import logging

from .db import count_documents_by_source, delete_by_source, insert_documents_batch
from .embeddings import get_embedding

logger = logging.getLogger("rag.dp_knowledge_seed")

SOURCE = "dp-assistant-demo"

DOCS = [
    {
        "chunk_index": 0,
        "content": (
            "The Data Processing App chat assistant must always query the Vector DB first. "
            "The vector database is the first source of truth for retrieval and orchestration decisions."
        ),
    },
    {
        "chunk_index": 1,
        "content": (
            "For general architecture questions, the assistant should answer from Vector DB only. "
            "It should not query the Data Processing DB or web search unless the question requires structured internal data or current external data."
        ),
    },
    {
        "chunk_index": 2,
        "content": (
            "The assistant should query the Data Processing DB only for structured internal data such as audit history, "
            "hidden metadata, processing failures, validation results, npm package processing jobs, and cross-reference tables."
        ),
    },
    {
        "chunk_index": 3,
        "content": (
            "The assistant should query web search only for external or current data such as latest npm package versions, "
            "current CVEs, current release notes, security advisories, or recent ecosystem information."
        ),
    },
    {
        "chunk_index": 4,
        "content": (
            "Demo questions should include vector-only, vector plus Data Processing DB, vector plus web search, "
            "and vector plus Data Processing DB plus web search answers. Responses must show which sources and tools were used."
        ),
    },
    {
        "chunk_index": 5,
        "content": (
            "The Data Processing App includes aggregation modules that calculate derived time-window results "
            "from incoming datapoints. Aggregation runs are tracked with audit information such as rule id, "
            "aggregation name, window start, window end, started at, completed at, status, processed count, "
            "inserted count, and message."
        ),
    },
    {
        "chunk_index": 6,
        "content": (
            "Aggregation audit data belongs to the Data Processing DB, not the Vector DB. "
            "The assistant should use Vector DB first for retrieval, then query the Data Processing DB when the user asks "
            "for structured aggregation run details, audit history, execution status, processed counts, inserted counts, "
            "or run messages."
        ),
    },
    {
        "chunk_index": 7,
        "content": (
            "The Data Processing App includes validation modules that evaluate incoming datapoints and formula-related values "
            "against validation rules. Validation-related information can include rule names, validation variables, "
            "pass or fail outcomes, severity, and corrective or blocking behavior."
        ),
    },
    {
        "chunk_index": 8,
        "content": (
            "When a question asks why a processing result failed, which validation rule triggered, which audit events happened, "
            "or what internal metadata caused a decision, the assistant should query the Data Processing DB after checking the Vector DB first."
        ),
    },
    {
        "chunk_index": 9,
        "content": (
            "The Data Processing App includes formula and calculation modules. Formula workflows can reference datapoints, "
            "formula variables, imported formula bundles, calculated outputs, and formula result snapshots. "
            "Cross-reference paths between formulas, validations, and processing jobs may require structured lookup from the Data Processing DB."
        ),
    },
    {
        "chunk_index": 10,
        "content": (
            "Questions about how formulas, aggregations, and validations work at an architecture level should usually be answered "
            "from Vector DB context. Questions about specific runs, statuses, audit records, counts, validation outcomes, "
            "or internal metadata should add Data Processing DB context."
        ),
    },
    {
        "chunk_index": 11,
        "content": (
            "The assistant should keep module boundaries clear: Vector DB is used first for retrieval and orchestration guidance, "
            "Data Processing DB is used for structured internal records, and web search is used only for external or current facts."
        ),
    },
]



def seed_dp_assistant_knowledge(replace_existing: bool = True) -> None:
    if replace_existing:
        delete_by_source(SOURCE)

    existing_count = count_documents_by_source(SOURCE)
    if existing_count > 0:
        logger.info("dp assistant knowledge already seeded")
        return

    rows = []
    for doc in DOCS:
        rows.append(
            {
                "source": SOURCE,
                "page_start": 1,
                "page_end": 1,
                "chunk_index": doc["chunk_index"],
                "content": doc["content"],
                "embedding": get_embedding(doc["content"]),
            }
        )

    insert_documents_batch(rows)
    logger.info("seeded %d dp assistant knowledge chunks", len(rows))

