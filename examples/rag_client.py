"""Minimal gen-api client for RAG pipelines.

Copy this module into your RAG codebase (or install httpx and import it as-is).

    client = GenSearchClient("http://localhost:8000", api_key="...")
    context = client.snippets("attention is all you need", num=5)
"""
from typing import Any

import httpx


class GenSearchClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 15.0) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-API-KEY": api_key},
            timeout=timeout,
        )

    def search(self, q: str, **params: Any) -> dict[str, Any]:
        """Raw /search call. params: gl, hl, location, num, page, tbs, debug."""
        response = self._client.post("/search", json={"q": q, **params})
        response.raise_for_status()
        result: dict[str, Any] = response.json()
        return result

    def snippets(self, q: str, num: int = 5, **params: Any) -> list[str]:
        """Ready-to-embed context strings: 'title — snippet (url)'."""
        organic = self.search(q, num=num, **params).get("organic", [])
        return [
            f"{item['title']} — {item.get('snippet', '')} ({item['link']})"
            for item in organic
        ]

    def news(self, q: str, num: int = 10, **params: Any) -> list[dict[str, Any]]:
        response = self._client.post("/news", json={"q": q, "num": num, **params})
        response.raise_for_status()
        items: list[dict[str, Any]] = response.json().get("news", [])
        return items

    def close(self) -> None:
        self._client.close()


if __name__ == "__main__":
    import os
    import sys

    key = os.environ.get("GEN_API_KEY")
    if not key:
        sys.exit("set GEN_API_KEY first")
    client = GenSearchClient("http://localhost:8000", api_key=key)
    for line in client.snippets("attention is all you need", num=3):
        print(line)
    client.close()
