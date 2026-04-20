import os
import requests
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()

OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_EMBEDDING_MODEL = os.getenv(
    "OPENROUTER_EMBEDDING_MODEL"
)

client = OpenAI(
    base_url=OPENROUTER_BASE_URL,
    api_key=OPENROUTER_API_KEY,
)

def get_embedding(text: str) -> list[float]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Embedding alınacak text boş olamaz.")

    response = client.embeddings.create(
        model=OPENROUTER_EMBEDDING_MODEL,
        input=text,
    )

    return response.data[0].embedding