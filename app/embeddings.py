import os
import requests
from dotenv import load_dotenv

load_dotenv()

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def get_embedding(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Embedding üretmek için text boş olamaz.")

    response = requests.post(
        f"{OLLAMA_BASE_URL}/api/embed",
        json={
            "model": OLLAMA_EMBED_MODEL,
            "input": text,
        },
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()

    if "embeddings" in data and isinstance(data["embeddings"], list) and len(data["embeddings"]) > 0:
        embedding = data["embeddings"][0]
        if not isinstance(embedding, list):
            raise ValueError(f"Beklenmeyen embedding formatı: {data}")
        return embedding

    if "embedding" in data and isinstance(data["embedding"], list):
        return data["embedding"]

    raise ValueError(f"Beklenmeyen Ollama embedding cevabı: {data}")