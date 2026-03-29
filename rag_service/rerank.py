from typing import Sequence

import httpx


class CohereReranker:
    def __init__(self, api_key: str, top_n: int = 4):
        self.api_key = api_key
        self.top_n = top_n
        self.url = "https://api.cohere.ai/v1/rerank"

    async def rerank(self, query: str, docs: Sequence[str]) -> list[int]:
        if not docs:
            return []
        headers = {"Authorization": f"Bearer {self.api_key}"}
        payload = {"query": query, "documents": list(docs), "top_n": min(self.top_n, len(docs))}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self.url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        rankings = sorted(data.get("results", []), key=lambda r: r.get("index", 0))
        return [item["index"] for item in rankings]
