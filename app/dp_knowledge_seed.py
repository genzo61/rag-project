import logging

from .db import delete_by_source, insert_documents_batch, search_similar
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
]


def seed_dp_assistant_knowledge(replace_existing: bool = False) -> None:
    if replace_existing:
        delete_by_source(SOURCE)

    probe = get_embedding("Data Processing App vector retrieval")
    existing = search_similar(probe, limit=3, source=SOURCE)
    if existing:
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

