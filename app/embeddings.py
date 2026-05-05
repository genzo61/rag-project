import os
import logging
from time import sleep

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

logger = logging.getLogger("rag.embeddings")

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_EMBEDDING_MODEL = os.getenv(
    "OPENROUTER_EMBEDDING_MODEL"
)
EMBEDDING_MAX_RETRIES = int(os.getenv("EMBEDDING_MAX_RETRIES", "6"))
EMBEDDING_RETRY_DELAY_SECONDS = float(os.getenv("EMBEDDING_RETRY_DELAY_SECONDS", "0.5"))

client = OpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)

def get_embedding(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Embedding alınacak text boş olamaz.")

    last_error: Exception | None = None
    for attempt in range(1, EMBEDDING_MAX_RETRIES + 1):
        try:
            response = client.embeddings.create(
                model=OPENROUTER_EMBEDDING_MODEL,
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
