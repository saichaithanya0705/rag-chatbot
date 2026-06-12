from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from lxml import html

SNIPPET_FALLBACK_CONTENT_LIMIT = 1600


class WebSearchError(RuntimeError):
    """Base error for web-search failures."""


class WebSearchOfflineError(WebSearchError):
    """Raised when the search provider cannot be reached."""


@dataclass(frozen=True)
class WebSearchResult:
    title: str
    url: str
    snippet: str
    content: str
    published_at: str | None = None


class WebSearchService:
    def __init__(
        self,
        *,
        backend: str,
        region: str,
        max_results: int,
    ) -> None:
        self._preferred_backend = backend.lower()
        self._region = region
        self._max_results = max_results
        self._client = httpx.AsyncClient(
            timeout=8.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

    async def search(self, query: str) -> list[WebSearchResult]:
        last_error: WebSearchError | None = None
        offline_error: WebSearchOfflineError | None = None

        for backend in self._backend_order():
            try:
                if backend == "duckduckgo":
                    return await self._hydrate_results(await self._search_duckduckgo(query))
                return await self._hydrate_results(await self._search_brave(query))
            except WebSearchOfflineError as error:
                offline_error = error
                last_error = error
            except WebSearchError as error:
                last_error = error

        raise offline_error or last_error or WebSearchError("Web search is unavailable right now.")

    def _backend_order(self) -> list[str]:
        supported = ["brave", "duckduckgo"]
        if self._preferred_backend in supported:
            return [self._preferred_backend, *[item for item in supported if item != self._preferred_backend]]
        return supported

    async def _search_brave(self, query: str) -> list[WebSearchResult]:
        html_text = await self._fetch_html(
            "https://search.brave.com/search",
            params={"q": query, "source": "web"},
        )
        document = html.fromstring(html_text)
        nodes = document.xpath("//div[contains(@class, 'snippet')][@data-type='web']")
        results: list[WebSearchResult] = []
        seen_urls: set[str] = set()

        for node in nodes:
            link_nodes = [link for link in node.xpath(".//a[@href]") if str(link.get("href", "")).startswith("http")]
            if not link_nodes:
                continue

            url = str(link_nodes[0].get("href", "")).strip()
            if url in seen_urls:
                continue
            title = " ".join(link_nodes[0].text_content().split())
            snippet = self._extract_brave_snippet(node)
            if not title or not snippet:
                continue

            seen_urls.add(url)
            results.append(
                WebSearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    content="",
                )
            )
            if len(results) >= self._max_results:
                break

        if not results:
            raise WebSearchError("Brave search returned no usable results.")
        return results

    async def _search_duckduckgo(self, query: str) -> list[WebSearchResult]:
        html_text = await self._fetch_html(
            "https://html.duckduckgo.com/html/",
            params={"q": query, "kl": self._region},
            method="POST",
        )
        document = html.fromstring(html_text)
        result_nodes = document.xpath("//div[contains(@class, 'result')]")
        results: list[WebSearchResult] = []
        seen_urls: set[str] = set()

        for node in result_nodes:
            link_nodes = node.xpath(".//a[contains(@class, 'result__a')]")
            if not link_nodes:
                continue

            link = link_nodes[0]
            url = str(link.get("href", "")).strip()
            if url in seen_urls:
                continue
            title = " ".join(link.text_content().split())
            snippet_nodes = node.xpath(".//*[contains(@class, 'result__snippet')]")
            snippet = " ".join(
                " ".join(snippet_node.text_content().split()) for snippet_node in snippet_nodes
            ).strip()
            if not url.startswith("http") or not title or not snippet:
                continue
            seen_urls.add(url)
            results.append(
                WebSearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    content="",
                )
            )
            if len(results) >= self._max_results:
                break

        if not results:
            raise WebSearchError("DuckDuckGo returned no usable results.")
        return results

    async def _hydrate_results(self, results: list[WebSearchResult]) -> list[WebSearchResult]:
        candidate_results = results[: min(len(results), max(2, min(self._max_results, 3)))]
        fetched_pages = await asyncio.gather(
            *(self._fetch_result_page(result) for result in candidate_results),
            return_exceptions=True,
        )

        hydrated_results: list[WebSearchResult] = []
        for fallback_result, fetched_result in zip(candidate_results, fetched_pages, strict=False):
            if isinstance(fetched_result, WebSearchResult):
                hydrated_results.append(fetched_result)
                continue

            snippet_result = self._snippet_fallback_result(fallback_result)
            if snippet_result is not None:
                hydrated_results.append(snippet_result)

        if not hydrated_results:
            raise WebSearchError("Web search results could not be read.")
        return hydrated_results

    @staticmethod
    def _snippet_fallback_result(result: WebSearchResult) -> WebSearchResult | None:
        snippet = " ".join(result.snippet.split())
        if not snippet:
            return None

        return WebSearchResult(
            title=result.title,
            url=result.url,
            snippet=result.snippet,
            content=snippet[:SNIPPET_FALLBACK_CONTENT_LIMIT],
            published_at=result.published_at,
        )

    async def _fetch_result_page(self, result: WebSearchResult) -> WebSearchResult | None:
        try:
            html_text = await self._fetch_html(result.url, params={})
        except WebSearchError:
            return None

        content = self._extract_page_content(html_text)
        if not content:
            return None
        published_at = self._extract_publish_date(html_text)

        return WebSearchResult(
            title=result.title,
            url=result.url,
            snippet=result.snippet,
            content=content,
            published_at=published_at,
        )

    async def _fetch_html(
        self,
        url: str,
        *,
        params: dict[str, str],
        method: str = "GET",
    ) -> str:
        try:
            if method == "POST":
                response = await self._client.post(url, data=params)
            else:
                response = await self._client.get(url, params=params)
            response.raise_for_status()
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, OSError) as error:
            raise WebSearchOfflineError("No internet. Web search is unavailable right now.") from error
        except httpx.HTTPError as error:
            raise WebSearchError("Web search is unavailable right now.") from error

        return response.text

    async def aclose(self) -> None:
        await self._client.aclose()

    @staticmethod
    def _extract_brave_snippet(node) -> str:
        fallback_text = " ".join(node.text_content().split())
        snippet_candidates = node.xpath(
            ".//*[contains(@class, 'generic-snippet')]//*[contains(@class, 'content')]"
            " | .//*[contains(@class, 'description')]"
        )
        for candidate in snippet_candidates:
            text = " ".join(candidate.text_content().split())
            if text:
                return text
        return fallback_text

    @staticmethod
    def _extract_page_content(html_text: str) -> str:
        try:
            document = html.fromstring(html_text)
        except (ValueError, TypeError):
            return ""

        for node in document.xpath("//script | //style | //noscript | //svg"):
            node.drop_tree()

        for selector in ("//main", "//article", "//body"):
            for node in document.xpath(selector):
                text = " ".join(node.text_content().split())
                if text:
                    return text[:4000]

        return ""

    @staticmethod
    def _extract_publish_date(html_text: str) -> str | None:
        try:
            document = html.fromstring(html_text)
        except (ValueError, TypeError):
            return None

        for xpath_query in (
            "//meta[@property='article:published_time']/@content",
            "//meta[@property='article:modified_time']/@content",
            "//meta[@name='pubdate']/@content",
            "//meta[@name='publish_date']/@content",
            "//meta[@name='date']/@content",
            "//time[@datetime]/@datetime",
        ):
            values = [str(value).strip() for value in document.xpath(xpath_query)]
            for value in values:
                if value:
                    return value[:40]

        return None
