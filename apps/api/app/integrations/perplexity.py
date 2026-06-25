"""
Perplexity Integration — Web research and news enrichment.
Uses sonar-pro model (0.930 SimpleQA — best-in-class per Actively AI's own benchmarks).
"""
from typing import Optional
import httpx
import structlog
from app.config import get_settings

log = structlog.get_logger()


class PerplexityClient:
    """Async Perplexity API client for account news enrichment."""

    BASE_URL = "https://api.perplexity.ai"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    async def research_account(self, company_name: str) -> str:
        """
        Research recent news and intelligence about a company.
        Returns structured text with citations.
        Used by ResearcherAgent as input.
        """
        query = (
            f"Recent news about {company_name} in the last 7 days: "
            "funding announcements, leadership changes (CEO, VP, CXO level), "
            "product launches, major partnerships, regulatory issues, "
            "competitive moves, acquisition news, layoffs or headcount changes."
            "Return only confirmed news with dates. Be specific."
        )

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers=self.headers,
                json={
                    "model": "sonar-pro",
                    "messages": [{"role": "user", "content": query}],
                    "return_citations": True,
                    "search_recency_filter": "week",
                },
            )

            if resp.status_code == 429:
                log.warning("perplexity_rate_limited", company=company_name)
                return ""

            if resp.status_code != 200:
                log.error("perplexity_error", status=resp.status_code, company=company_name)
                return ""

            data = resp.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            citations = data.get("citations", [])

            # Append citations to content
            if citations:
                content += "\n\nSources:\n"
                for i, url in enumerate(citations[:5], 1):
                    content += f"{i}. {url}\n"

            log.info("perplexity_research_complete", company=company_name, chars=len(content))
            return content

    async def answer_question(self, question: str, context: str = "") -> str:
        """
        Answer a specific question using Perplexity web search.
        Used by the Assistant for real-time queries that need fresh data.
        """
        async with httpx.AsyncClient(timeout=20.0) as client:
            messages = []
            if context:
                messages.append({"role": "system", "content": context})
            messages.append({"role": "user", "content": question})

            resp = await client.post(
                f"{self.BASE_URL}/chat/completions",
                headers=self.headers,
                json={
                    "model": "sonar-pro",
                    "messages": messages,
                    "return_citations": True,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    async def check_people_signals(
        self,
        name: str,
        title: str,
        company: str,
    ) -> Optional[str]:
        """
        Search for recent job changes for a stakeholder via web/LinkedIn search.
        Returns a brief description of any role change found, or None.
        """
        # Use role and company only — avoid sending full names to third-party API (PII minimization)
        query = (
            f'Has the {title} at {company} recently changed jobs, '
            f"been promoted, or left the company? "
            f"Search LinkedIn and recent news from the last 30 days. "
            f"If no change found, say 'no change detected'. Be concise — one sentence."
        )
        try:
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(
                    f"{self.BASE_URL}/chat/completions",
                    headers=self.headers,
                    json={
                        "model": "sonar-pro",
                        "messages": [{"role": "user", "content": query}],
                        "return_citations": True,
                        "search_recency_filter": "month",
                    },
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content or "no change detected" in content.lower():
                    return None
                citations = data.get("citations", [])
                source = citations[0] if citations else None
                result = content[:400]
                if source:
                    result += f" (source: {source})"
                return result
        except Exception as e:
            log.debug(f"people_signal_check_failed name={name}: {e}")
            return None
