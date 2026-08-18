from balanceai_backend.config import settings
from tavily import TavilyClient


def search(query: str) -> str | None:
    client = TavilyClient(api_key=settings.tavily_api_key)
    result = client.search(query=query, max_results=1, search_depth="basic")
    results = result.get("results", [])
    return results[0].get("content", "") if results else None
