from __future__ import annotations

import asyncio
import unittest

from app.services.web_search_service import WebSearchResult, WebSearchService


class _HydrationFallbackWebSearchService(WebSearchService):
    def __init__(self, hydrated_result: WebSearchResult | None = None) -> None:
        super().__init__(backend="duckduckgo", region="us-en", max_results=3)
        self._hydrated_result = hydrated_result

    async def _fetch_result_page(self, result: WebSearchResult) -> WebSearchResult | None:
        if self._hydrated_result and result.url == self._hydrated_result.url:
            return self._hydrated_result
        return None


async def _hydrate_and_close(
    service: WebSearchService,
    results: list[WebSearchResult],
) -> list[WebSearchResult]:
    try:
        return await service._hydrate_results(results)
    finally:
        await service.aclose()


class WebSearchServiceTests(unittest.TestCase):
    def test_hydrate_results_falls_back_to_provider_snippets(self) -> None:
        service = _HydrationFallbackWebSearchService()
        results = asyncio.run(
            _hydrate_and_close(
                service,
                [
                    WebSearchResult(
                        title="OpenAI News",
                        url="https://openai.com/news/",
                        snippet="  Latest updates about OpenAI.  ",
                        content="",
                    )
                ],
            )
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "OpenAI News")
        self.assertEqual(results[0].url, "https://openai.com/news/")
        self.assertEqual(results[0].content, "Latest updates about OpenAI.")

    def test_hydrate_results_keeps_page_content_when_available(self) -> None:
        hydrated = WebSearchResult(
            title="Hydrated title",
            url="https://example.com/current",
            snippet="Snippet fallback",
            content="Full page content.",
            published_at="2026-06-12",
        )
        service = _HydrationFallbackWebSearchService(hydrated_result=hydrated)
        results = asyncio.run(
            _hydrate_and_close(
                service,
                [
                    WebSearchResult(
                        title="Search title",
                        url="https://example.com/current",
                        snippet="Snippet fallback",
                        content="",
                    )
                ],
            )
        )

        self.assertEqual(results, [hydrated])


if __name__ == "__main__":
    unittest.main()
