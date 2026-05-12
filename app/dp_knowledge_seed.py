import logging

from .db import count_documents_by_source, delete_by_source, insert_documents_batch
from .dp_schema import build_rag_schema_documents
from .embeddings import get_embedding

logger = logging.getLogger("rag.dp_knowledge_seed")

SOURCE = "dp-assistant-demo"

BASE_DOCS = [
    (
        "The Data Processing App chat assistant must always query the Vector DB first. "
        "The vector database is the first source of truth for retrieval and orchestration decisions."
    ),
    (
        "For general architecture questions, the assistant should answer from Vector DB only. "
        "It should not query the Data Processing DB or web search unless the question requires structured internal data or current external data."
    ),
    (
        "The assistant should query the Data Processing DB only for structured internal data such as audit history, "
        "snapshots, validation mappings, formula mappings, aggregation run records, internal processing jobs, and cross-reference tables."
    ),
    (
        "The assistant should query web search only for external or current data such as latest npm package versions, "
        "current CVEs, current release notes, security advisories, or recent ecosystem information."
    ),
    (
        "Demo answers should clearly separate which evidence came from Vector DB, Data Processing DB, and web search."
    ),
]


def _build_docs() -> list[dict[str, object]]:
    docs = [*BASE_DOCS, *build_rag_schema_documents()]
    return [
        {
            "chunk_index": index,
            "content": content,
        }
        for index, content in enumerate(docs)
    ]


def seed_dp_assistant_knowledge(replace_existing: bool = True) -> None:
    if replace_existing:
        delete_by_source(SOURCE)

    existing_count = count_documents_by_source(SOURCE)
    if existing_count > 0:
        logger.info("dp assistant knowledge already seeded")
        return

    rows = []
    for doc in _build_docs():
        rows.append(
            {
                "source": SOURCE,
                "page_start": 1,
                "page_end": 1,
                "chunk_index": doc["chunk_index"],
                "content": doc["content"],
                "embedding": get_embedding(str(doc["content"])),
            }
        )

    insert_documents_batch(rows)
    logger.info("seeded %d dp assistant knowledge chunks", len(rows))
