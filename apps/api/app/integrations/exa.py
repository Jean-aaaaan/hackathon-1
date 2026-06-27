"""
Exa Integration — Semantic web research for account and stakeholder intelligence.
Uses Exa's neural search to find recent news, leadership changes, and competitive signals.
Replaces Perplexity as the primary web research layer when EXA_API_KEY is set.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import httpx
import structlog

log = structlog.get_logger()

_BASE_URL = "https://api.exa.ai"
_SEARCH_RECENCY_DAYS = 30
_MAX_CHARS_PER_RESULT = 800
_NUM_RESULTS = 5


class ExaClient:
    """Async Exa API client for account and stakeholder research."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "x-api-key": api_key,
            "Content-Type": "application/json",
        }

    def _cutoff_date(self, days: int = _SEARCH_RECENCY_DAYS) -> str:
        dt = datetime.now(timezone.utc) - timedelta(days=days)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    async def research_account(self, company_name: str) -> str:
        """
        Search for recent news and intelligence about a company.
        Returns structured text with titles, URLs, and snippets.
        Passed to ResearcherAgent as news_content.
        """
        query = (
            f"{company_name} company news funding leadership changes "
            "acquisition layoffs product launch partnership 2024 2025"
        )

        payload = {
            "query": query,
            "numResults": _NUM_RESULTS,
            "type": "neural",
            "startPublishedDate": self._cutoff_date(),
            "useAutoprompt": True,
            "contents": {
                "text": {"maxCharacters": _MAX_CHARS_PER_RESULT},
            },
        }

        async with httpx.AsyncClient(timeout=25.0) as client:
            try:
                resp = await client.post(
                    f"{_BASE_URL}/search",
                    headers=self.headers,
                    json=payload,
                )
            except httpx.TimeoutException:
                log.warning("exa_timeout", company=company_name)
                return ""

            if resp.status_code == 429:
                log.warning("exa_rate_limited", company=company_name)
                return ""

            if resp.status_code != 200:
                log.error("exa_error", status=resp.status_code, company=company_name, body=resp.text[:200])
                return ""

            data = resp.json()
            results = data.get("results", [])
            if not results:
                log.info("exa_no_results", company=company_name)
                return ""

            sections = [f"=== Exa Web Intelligence: {company_name} (last {_SEARCH_RECENCY_DAYS} days) ==="]
            for r in results:
                title = r.get("title", "").strip()
                url = r.get("url", "")
                published = (r.get("publishedDate") or "")[:10]
                text = (r.get("text") or "").strip()
                if not text:
                    continue
                sections.append(f"\n[{published}] {title}\nURL: {url}\n{text}")

            content = "\n".join(sections)
            log.info("exa_research_complete", company=company_name, results=len(results), chars=len(content))
            return content

    async def check_people_signals(
        self,
        name: str,
        title: str,
        company: str,
    ) -> Optional[str]:
        """
        Search for recent job changes or role updates for a key stakeholder.
        Returns a brief description if a change is detected, or None.
        """
        query = f"{title} {company} job change promotion departure LinkedIn"

        payload = {
            "query": query,
            "numResults": 3,
            "type": "neural",
            "startPublishedDate": self._cutoff_date(days=60),
            "useAutoprompt": False,
            "contents": {
                "text": {"maxCharacters": 400},
            },
        }

        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    f"{_BASE_URL}/search",
                    headers=self.headers,
                    json=payload,
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                results = data.get("results", [])
                if not results:
                    return None

                # Score results for relevance — look for departure/promotion keywords
                change_keywords = {"left", "departed", "resigned", "promoted", "joined", "appointed", "no longer"}
                for r in results:
                    text = (r.get("text") or "").lower()
                    if any(kw in text for kw in change_keywords):
                        snippet = (r.get("text") or "")[:300].strip()
                        url = r.get("url", "")
                        result = f"{snippet}"
                        if url:
                            result += f" (source: {url})"
                        return result

                return None

        except Exception as e:
            log.debug("exa_people_signal_failed", name=name, error=str(e))
            return None
