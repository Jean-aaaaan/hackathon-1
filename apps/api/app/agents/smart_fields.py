"""
SmartFieldsAgent — CRM hygiene engine.
Model: Claude Haiku 4.5 (fast, cheap, structured output)
Cost: ~$0.01/account

Purpose: After each agent run, compare what AI knows vs what's in HubSpot.
Surface field update suggestions where the AI has higher-confidence data.

Fields covered:
  hs_forecast_category  — AI POV vs CRM forecast (most impactful)
  closedate             — Timeline risk vs stated close date
  amount                — Deal size changes mentioned in calls/notes
  notes_next_activity_date — Based on top priority action

CRM accuracy rule: Only surface when confidence >= 0.65 AND current value
materially differs from suggested value. Never hallucinate field values.
Each suggestion must cite the specific source signal.
"""
import json
from app.agents.base import (
    BaseAgent, SmartFieldsResult,
    RiskResult, PrioritiserResult, GroundingResult, ResearchResult
)
import structlog

log = structlog.get_logger()

SMART_FIELDS_SYSTEM_PROMPT = """You are a CRM accuracy agent. Your job is to compare what the AI pipeline knows
about a deal with what is currently stored in HubSpot, and flag fields that should be updated.

==============================================================================
FIELDS YOU CAN SUGGEST UPDATES FOR
==============================================================================

hs_forecast_category:
  Allowed values: Pipeline | Best Case | Commit | Omit
  Suggest when: AI POV category differs from CRM category by one or more levels.
  Example: AI says "Best Case" but CRM says "Pipeline" — suggest updating.
  Confidence: use AI POV forecast_confidence directly.
  Impact: HIGH — affects pipeline reporting and forecasting accuracy.

closedate:
  Format: YYYY-MM-DD
  Suggest when: timeline_risk = high or critical AND close date is within 60 days without a MAP.
  OR: AI has specific evidence (from Gong call / note) of a new target date.
  Confidence: 0.7 for timeline risk inference, 0.85+ if explicitly mentioned in source.
  Impact: HIGH — close date slip is the #1 indicator of deal health decline.

amount:
  Format: numeric value as string (e.g. "125000")
  Suggest when: A specific deal amount was mentioned in a call, email, or note that differs
  from the current amount. NEVER estimate — only suggest if explicitly stated in a source.
  Confidence: 0.8+ only.
  Impact: MEDIUM — affects pipeline value reporting.

notes_next_activity_date:
  Format: YYYY-MM-DD
  Suggest when: The top priority action has an implied timeline and next activity is not set
  or is in the past. Derive a date from "DO TODAY" or "DO THIS WEEK" action urgency.
  Impact: LOW — helps rep stay on top of follow-up cadence.

==============================================================================
SUGGESTION RULES
==============================================================================

1. NEVER suggest a field update without a specific cited source.
2. Only surface suggestions with confidence >= 0.65. Below that, skip it.
3. Maximum 5 suggestions total. Prioritise by impact: HIGH > MEDIUM > LOW.
4. hs_forecast_category is the most valuable suggestion — always evaluate it first.
5. If current value and suggested value are identical, do NOT include it.
6. For closedate: use evidence from deal_velocity_signals or explicit mentions.
7. For amount: ONLY suggest if a specific number was mentioned — never calculate or infer.
8. Write the reason as if briefing a sales manager: specific, factual, no hedging.

==============================================================================
MEDDPICC LINKAGE
==============================================================================

Map each suggestion to the MEDDPICC component it improves:
- hs_forecast_category → "General" (POV accuracy)
- closedate → "Paper Process" or "Timeline"
- amount → "Metrics" or "Economic Buyer"
- notes_next_activity_date → the MEDDPICC component of the top action

Return empty suggestions list if no field updates are warranted."""


class SmartFieldsAgent(BaseAgent):
    """
    Compares AI pipeline output vs current HubSpot field values.
    Returns field update suggestions with evidence and confidence scores.
    """

    async def run(
        self,
        account_name: str,
        current_state: dict,
        risk_result: RiskResult,
        prioritiser_result: PrioritiserResult,
        grounding_result: GroundingResult,
        research_result: ResearchResult,
    ) -> SmartFieldsResult:

        # Current HubSpot values (from state)
        crm_forecast = current_state.get("crm_forecast_category") or "Unknown"
        crm_close_date = current_state.get("close_date") or "Not set"
        crm_amount = current_state.get("deal_amount") or 0
        crm_next_activity = current_state.get("next_activity") or "Not set"

        # AI assessments
        ai_forecast = risk_result.pov_forecast_category
        ai_confidence = risk_result.pov_forecast_confidence
        timeline_risk = risk_result.timeline_risk
        deal_momentum = risk_result.deal_momentum
        close_date_integrity = risk_result.close_date_integrity

        # Top priority action (for next activity date)
        top_action = prioritiser_result.next_actions[0] if prioritiser_result.next_actions else None

        # Velocity signals
        velocity = research_result.deal_velocity_signals or {}

        # Verified signals (evidence for field suggestions)
        verified_signals = [s.model_dump() for s in grounding_result.verified_signals[:5]]

        import html as _html

        def _q(v: str) -> str:
            return _html.escape(str(v))

        user_message = f"""
<deal_context>
Account: {_q(account_name)}
Stage: {_q(current_state.get('stage', 'Unknown'))}
Deal Amount: ${crm_amount:,.0f}
Today's Date: Use current context
</deal_context>

=== CURRENT HUBSPOT FIELD VALUES ===
hs_forecast_category: {_q(crm_forecast)}
closedate: {_q(str(crm_close_date))}
amount: ${crm_amount:,.0f}
notes_next_activity_date: {_q(str(crm_next_activity))}

=== AI PIPELINE OUTPUTS ===
AI POV Category: {_q(str(ai_forecast))} (confidence: {ai_confidence or 0:.0%})
Timeline Risk: {_q(str(timeline_risk))}
Deal Momentum: {_q(str(deal_momentum))}
Close Date Integrity: {_q(str(close_date_integrity))}
Health Score: {risk_result.health_score or 0:.2f}

Top Risk: {_q(str(prioritiser_result.top_risk_summary))}

=== TOP PRIORITY ACTION ===
{json.dumps(top_action.model_dump() if top_action else {}, indent=2)}

=== DEAL VELOCITY SIGNALS ===
Days in stage: {velocity.get('days_in_stage', 'unknown')}
Close date slips: {velocity.get('close_date_slips', 0)}
Last meaningful activity: {velocity.get('last_meaningful_activity_days', 'unknown')} days ago
Engagement trend: {velocity.get('engagement_trend', 'unknown')}

=== VERIFIED INTELLIGENCE (source evidence for field updates) ===
{json.dumps(verified_signals, indent=2)}

=== PREVIOUS SMART FIELD SUGGESTIONS (do NOT repeat applied/dismissed ones) ===
{json.dumps([
    s for s in current_state.get('smart_fields', [])
    if s.get('status') in ('applied', 'dismissed')
], indent=2)}

Evaluate each of the 4 mappable HubSpot fields. For each where you have clear evidence
of a needed update, include a suggestion. For fields that are already accurate or where
you lack evidence, do not include them.
"""

        result_dict = await self._call_llm(
            system_prompt=SMART_FIELDS_SYSTEM_PROMPT,
            user_message=user_message,
            tool_name="smart_fields_result",
            tool_schema=SmartFieldsResult.model_json_schema(),
            max_tokens=1500,
        )

        result = self.parse_output(SmartFieldsResult, result_dict)

        # Filter to >= 0.65 confidence only
        result = SmartFieldsResult(
            suggestions=[s for s in result.suggestions if s.confidence >= 0.65],
            fields_scanned=result.fields_scanned,
            meddpicc_gaps_addressed=result.meddpicc_gaps_addressed,
            reasoning=result.reasoning,
        )

        log.info(
            "smart_fields_complete",
            account=account_name,
            suggestions=len(result.suggestions),
            fields=[s.field_label for s in result.suggestions],
        )
        return result
