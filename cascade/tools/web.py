"""Web tools — URL fetching and web search."""

from __future__ import annotations

from typing import Any

import httpx

from cascade.tools.base import BaseTool, Tier, ToolResult


class FetchURLTool(BaseTool):
    """Fetch content from a URL."""

    name = "fetch_url"
    description = (
        "Fetch the content of a web page and return it as text. "
        "HTML is converted to readable text. Useful for reading documentation."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL to fetch.",
            },
        },
        "required": ["url"],
    }
    allowed_tiers = {Tier.T1, Tier.T2}

    async def execute(self, **kwargs: Any) -> ToolResult:
        url = kwargs.get("url", "")
        if not url:
            return ToolResult(success=False, error="No URL provided")

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "Cascade-AI/0.1"},
            ) as client:
                resp = await client.get(url)
                resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")

            if "text/html" in content_type:
                # Convert HTML to text
                text = self._html_to_text(resp.text)
            else:
                text = resp.text

            # Truncate very long content
            max_len = 15000
            if len(text) > max_len:
                text = text[:max_len] + f"\n... (truncated, {len(text)} total chars)"

            return ToolResult(output=text)
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, error=f"HTTP {e.response.status_code}: {url}")
        except Exception as e:
            return ToolResult(success=False, error=f"Error fetching URL: {e}")

    @staticmethod
    def _html_to_text(html: str) -> str:
        """Convert HTML to readable text."""
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")

            # Remove script and style elements
            for element in soup(["script", "style", "nav", "footer", "header"]):
                element.decompose()

            text = soup.get_text(separator="\n", strip=True)
            # Clean up multiple blank lines
            lines = [line.strip() for line in text.splitlines()]
            lines = [line for line in lines if line]
            return "\n".join(lines)
        except ImportError:
            # Fallback: strip tags with regex
            import re

            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text


class WebSearchTool(BaseTool):
    """Search the web for information."""

    name = "web_search"
    description = (
        "Search the web for information using DuckDuckGo. "
        "Returns a list of results with titles, URLs, and snippets."
    )
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of results. Default is 5.",
            },
        },
        "required": ["query"],
    }
    allowed_tiers = {Tier.T1, Tier.T2}

    async def execute(self, **kwargs: Any) -> ToolResult:
        query = kwargs.get("query", "")
        max_results = kwargs.get("max_results", 5)

        if not query:
            return ToolResult(success=False, error="No search query provided")

        try:
            from duckduckgo_search import DDGS

            results: list[str] = []
            with DDGS() as ddgs:
                for r in ddgs.text(query, max_results=max_results):
                    results.append(
                        f"**{r.get('title', 'No title')}**\n"
                        f"  URL: {r.get('href', '')}\n"
                        f"  {r.get('body', '')}"
                    )

            if not results:
                return ToolResult(output=f"No results found for: {query}")

            return ToolResult(output="\n\n".join(results))
        except ImportError:
            return ToolResult(
                success=False,
                error="duckduckgo-search not installed. Run: pip install duckduckgo-search",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Search error: {e}")
