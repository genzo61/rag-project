import os
import logging
from time import sleep

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger("rag.embeddings")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_EMBEDDING_MODEL = os.getenv("OPENROUTER_EMBEDDING_MODEL", "")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "ollama")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "")
LLM_BACKEND = os.getenv("LLM_BACKEND", "openrouter").strip().lower()
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "6"))
EMBEDDING_RETRY_DELAY_SECONDS = float(os.getenv("EMBEDDING_RETRY_DELAY_SECONDS", "0.5"))

if LLM_BACKEND == "ollama":
    EMBEDDING_BASE_URL = OLLAMA_BASE_URL.rstrip("/")
    if not EMBEDDING_BASE_URL.endswith("/v1"):
        EMBEDDING_BASE_URL = f"{EMBEDDING_BASE_URL}/v1"
    EMBEDDING_API_KEY = OLLAMA_API_KEY
    EMBEDDING_MODEL = OLLAMA_EMBED_MODEL
else:
    EMBEDDING_BASE_URL = OPENROUTER_BASE_URL
    EMBEDDING_API_KEY = OPENROUTER_API_KEY
    EMBEDDING_MODEL = OPENROUTER_EMBEDDING_MODEL

client = OpenAI(
    base_url=EMBEDDING_BASE_URL,
    api_key=EMBEDDING_API_KEY,
)

def get_embedding(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Embedding alınacak text boş olamaz.")

    last_error: Exception | None = None
    if not EMBEDDING_MODEL:
        raise RuntimeError(
            "Embedding model is not configured. Set OPENROUTER_EMBEDDING_MODEL or OLLAMA_EMBED_MODEL."
        )

    for attempt in range(1, EMBEDDING_MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=text,
            )

            if not response.data:
                raise ValueError("No embedding data received")

            embedding = response.data[0].embedding
            if not embedding:
                raise ValueError("Empty embedding received")

            return embedding
        except Exception as exc:
            last_error = exc
            if attempt >= EMBEDDING_MAX_RETRIES:
                break

            logger.warning(
                "Embedding request failed on attempt %d/%d: %s",
                attempt,
                EMBEDDING_MAX_RETRIES,
                exc,
            )
            sleep(EMBEDDING_RETRY_DELAY_SECONDS * attempt)

    raise RuntimeError(
        f"Embedding alınamadı ({EMBEDDING_MAX_RETRIES} deneme): {last_error}"
    ) from last_error
