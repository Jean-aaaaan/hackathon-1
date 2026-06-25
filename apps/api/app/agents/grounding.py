"""
GroundingAgent — Fact verification layer. GA from Day 1.
Model: Claude Haiku 4.5
Cost: ~$0.02/account

This is our key differentiator vs Actively AI:
- Actively's grounding agent is in beta (feature flag: has_grounding_agent_access)
- Ours ships verified from day 1, and the audit trail is visible to reps
- Every fact in the Assistant has: source, confidence, conflict resolution history
- Reps can click any fact to see the full Gold Data audit trail
"""
import json
from app.agents.base import (
    BaseAgent, GroundingResult, ResearchResult, RiskResult,
    GoldDataPoint, SignalOut
)
import structlog

log = structlog.get_logger()

GROUNDING_SYSTEM_PROMPT = """You are a fact verification specialist. Your job is to verify
every claim against its cited source before it reaches the sales rep.

VERIFICATION RULES:
1. Every signal must have a plausible, specific source (not just "various sources")
2. Signals from Gong calls: verify the transcript snippet supports the claim
3. Signals from HubSpot: verify the field/timestamp makes sense
4. Signals from news/Perplexity: verify the news item is recent (<7 days) and relevant
5. If a signal cannot be verified, mark as "unverified" — do NOT discard it, flag it

GOLD DATA LAYER:
For any fact appearing in multiple sources with conflicts, build a gold_data_point:
- List all sources with their values and confidence scores
- Apply recency weighting (newer = higher weight)
- Resolve to the most likely truth
- Store the full audit trail for the Audit Panel

NEVER:
- Remove a signal just because you can't verify it (flag instead)
- Add your own confidence if the original source confidence is provided
- Change the urgency_score by more than 0.1 in either direction

OUTPUT FORMAT:
- verified_signals: signals that pass verification (unchanged or slightly adjusted)
- unverified_claims: signals that couldn't be verified (flagged with reason)
- gold_data_points: resolved conflicts with full audit trail"""


class GroundingAgent(BaseAgent):
    """
    Verifies every fact before it surfaces to the rep.
    Produces the Gold Data Layer with full audit trail.
    """

    async def run(
        self,
        account_name: str,
        current_state: dict,
        research_result: ResearchResult,
        risk_result: RiskResult,
    ) -> GroundingResult:

        all_signals = research_result.new_signals + risk_result.risks

        # Cap signals to prevent oversized prompts — grounding works on extracted signals,
        # not raw email text. Prioritise by urgency score, take top 30.
        if len(all_signals) > 30:
            all_signals = sorted(all_signals, key=lambda s: s.urgency_score, reverse=True)[:30]

        # Truncate signal detail to 300 chars for grounding (full detail is in researcher context)
        signals_for_grounding = []
        for s in all_signals:
            d = s.model_dump()
            if d.get("detail") and len(d["detail"]) > 300:
                d["detail"] = d["detail"][:300] + "…"
            signals_for_grounding.append(d)

        import html as _html

        def _q(v: str) -> str:
            return _html.escape(str(v))

        user_message = f"""
<deal_context>
Account: {_q(account_name)}
</deal_context>

=== SIGNALS TO VERIFY ({len(signals_for_grounding)} total) ===
{json.dumps(signals_for_grounding, indent=2)}

=== CURRENT ACCOUNT STATE (for cross-reference) ===
Summary: {_q(current_state.get('summary', 'None'))}
Key Stakeholders: {json.dumps([{k: v for k, v in s.items() if k in ('name','role','engagement_level')} for s in current_state.get('stakeholders', [])[:5]], indent=2)}
Existing Gold Data keys: {list(current_state.get('gold_data', {}).keys())}

For each signal: verify the source is specific and plausible, flag conflicts, build Gold Data audit trail for resolved conflicts.
"""

        result_dict = await self._call_llm(
            system_prompt=GROUNDING_SYSTEM_PROMPT,
            user_message=user_message,
            tool_name="grounding_result",
            tool_schema=GroundingResult.model_json_schema(),
            max_tokens=3000,
        )

        result = self.parse_output(GroundingResult, result_dict)
        log.info(
            "grounding_complete",
            account=account_name,
            verified=len(result.verified_signals),
            unverified=len(result.unverified_claims),
            overall_confidence=result.overall_confidence,
        )
        return result
