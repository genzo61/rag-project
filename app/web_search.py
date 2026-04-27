import os
import requests
from urllib.parse import urlparse


SEARXNG_BASE_URL = os.getenv("SEARXNG_BASE_URL")


def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""


def web_search(query: str, max_results: int = 5) -> list[dict]:
    """
    SearXNG üzerinden web araması yapar.
    Dönen sonuçları normalize eder: title, url, content, source.
    """

    url = f"{SEARXNG_BASE_URL}/search"

    params = {
        "q": query,
        "format": "json",
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"[WEB_SEARCH_ERROR] {e}")
        return []

    data = response.json()
    raw_results = data.get("results", [])

    results = []

    for item in raw_results:
        title = item.get("title") or ""
        result_url = item.get("url") or ""
        content = item.get("content") or item.get("snippet") or ""

        if not title or not result_url:
            continue

        results.append(
            {
                "title": title,
                "url": result_url,
                "content": content,
                "source": get_domain(result_url),
            }
        )

        if len(results) >= max_results:
            break

    return results


def build_web_context(results: list[dict]) -> str:
    """
    Web sonuçlarını LLM prompt'una verilecek context formatına çevirir.
    """

    if not results:
        return ""

    blocks = []

    for i, result in enumerate(results, start=1):
        blocks.append(
            f"""Source {i}
Title: {result["title"]}
URL: {result["url"]}
Content: {result["content"]}
"""
        )

    return "\n".join(blocks)