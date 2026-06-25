"""
AssistantService — Streaming chat grounded on Account State Object.
Every response is grounded on Gold Data — facts are cited, auditable.
Thread history persisted in PostgreSQL (JSONB) — no Redis dependency.
"""
import html as _html
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Optional, AsyncGenerator
from anthropic import AsyncAnthropic
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, desc
import structlog

from app.config import get_settings
from app.models.account import Account
from app.integrations.perplexity import PerplexityClient
from app.agents.drafter import strip_dashes

log = structlog.get_logger()

# Thread storage table (created in migration)
# conversations(id, user_id, workspace_id, account_id, messages JSONB, created_at, updated_at)


def _fmt_amount(deal_amount, fallback: str = "Unknown") -> str:
    """Format a deal amount as a dollar string, or return fallback when absent."""
    return f"${float(deal_amount):,.0f}" if deal_amount else fallback


def _risk_text(r: object) -> str:
    """Normalize a risk entry that may be a plain string or a dict with description/detail."""
    return r if isinstance(r, str) else r.get("description", "") or r.get("detail", "") or ""


def _is_valid_uuid(val: str) -> bool:
    """Return True only when val is a well-formed UUID (guards raw SQL params)."""
    try:
        uuid.UUID(val)
        return True
    except (ValueError, AttributeError):
        return False


def _build_system_prompt(seller_context: dict | None = None) -> str:
    sc = seller_context or {}
    sender_name    = _html.escape(sc.get("sender_name") or "the rep")
    sender_title   = _html.escape(sc.get("sender_title") or "rep")
    sender_company = _html.escape(sc.get("sender_company") or "your company")
    return f"""You are Vantage, the sales intelligence assistant helping {sender_name} ({sender_title}) at {sender_company} close enterprise deals.

You are helping a SELLER. Every account in the data below is a PROSPECT or CUSTOMER that {sender_company} is selling to. All contacts and stakeholders listed are BUYERS at those companies — they are NOT {sender_company} colleagues. When advising on next steps or drafting language, always write from {sender_company}'s perspective as the seller, never from inside the buyer's organization.

You have account data loaded below (or portfolio-level data when no account is scoped).
Only state facts that appear in that data. When you cite a fact, add its source in brackets: [HubSpot], [Fireflies], [Perplexity].

Rules:
- Lead with what {sender_name} should do. Background comes second.
- Use plain bullets, not paragraphs.
- If data is missing or thin (agent hasn't run yet), say so briefly and suggest running the agent.
- Never fabricate contacts, deal amounts, or dates.
- When uncertainty exists, flag it: "unverified; confirm with [contact]".
"""


class AssistantService:
    """Manages streaming chat sessions grounded on account data."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()
        # Single client shared across stream_response + build_meeting_brief; both use the
        # same api_key and there is no per-request state on AsyncAnthropic itself.
        self._anthropic = AsyncAnthropic(api_key=self.settings.anthropic_api_key)

    async def stream_response(
        self,
        workspace_id: str,
        user_id: str,
        message: str,
        account: Optional[Account],
        thread_id: str,
        use_perplexity: bool = False,
        seller_context: dict | None = None,
    ) -> AsyncGenerator[dict, None]:
        """
        Stream a response grounded on account data.
        Yields chunks: {"type": "text", "text": "..."} or {"type": "citation", "citation": {...}}
        """
        # Responder fast path: check pre-compressed context cache first
        context = ""
        if account:
            from app.services.cache import get_compressed_context
            cached_ctx = await get_compressed_context(str(account.id), workspace_id)
            if cached_ctx:
                context = cached_ctx
            else:
                context = self._build_context(account)
        else:
            portfolio_context = await self._build_workspace_context(workspace_id)
            if portfolio_context:
                context = portfolio_context

        # Load thread history
        history = await self._get_thread_messages(thread_id, user_id, workspace_id)

        messages = await self._build_messages(history, message, account, use_perplexity)

        # System prompt with seller identity + account context
        system = _build_system_prompt(seller_context)
        if context:
            system += f"\n\n## Current Account Context\n{context}"

        # Stream from Claude
        full_response = ""
        # 0 is the sentinel for an interrupted stream; set to real usage only after get_final_message()
        token_count = 0

        try:
            async with self._anthropic.messages.stream(
                model=self.settings.anthropic_model_quality,
                max_tokens=2000,
                system=system,
                messages=messages,
            ) as stream:
                async for text_chunk in stream.text_stream:
                    full_response += text_chunk
                    yield {"type": "text", "text": text_chunk}

                final = await stream.get_final_message()
                token_count = final.usage.input_tokens + final.usage.output_tokens

            # Extract citations from response
            citations = self._extract_citations(full_response, account)
            for citation in citations:
                yield {"type": "citation", "citation": citation}

            # Persist to thread
            messages.append({"role": "assistant", "content": full_response})
            await self._save_thread(
                thread_id=thread_id,
                user_id=user_id,
                workspace_id=workspace_id,
                account_id=str(account.id) if account else None,
                messages=messages,
            )

            yield {"type": "done", "tokens": token_count}

        except Exception as e:
            log.error("assistant_stream_error", error=str(e), thread_id=thread_id, exc_info=True)
            yield {"type": "error", "message": "Stream interrupted. Please retry."}

    async def build_meeting_brief(
        self,
        account: Account,
        workspace_id: str,
        meeting_context: Optional[str] = None,
        seller_context: dict | None = None,
    ) -> dict:
        """
        Build a structured meeting brief for an account.
        Non-streaming — called pre-meeting for instant readout.
        """
        state = account.state or {}
        pov = state.get("pov", {})
        # Slice to 5 here — prompt uses [:3] and return dict uses [:3]/[:5]; no need for an
        # intermediate [:10] buffer when the max downstream consumption is 5 items.
        signals = state.get("signals", [])[:5]
        next_actions = state.get("next_actions", [])
        stakeholders = state.get("stakeholders", [])

        _amount_str = _fmt_amount(account.deal_amount)
        _safe_name  = _html.escape(str(account.name or ""))
        _safe_stage = _html.escape(str(account.stage or "Unknown"))
        prompt = f"""Write a pre-meeting brief for: {_safe_name}

Account data:
- Stage: {_safe_stage}
- Deal amount: {_amount_str}
- Close date: {str(account.close_date) if account.close_date else 'Unknown'}
- Health score: {account.health_score or 'Unknown'}/1.0
- AI forecast: {pov.get('forecast_category', 'Unknown')} ({pov.get('forecast_confidence') or 0:.0%} confidence)

Top signals: {json.dumps(signals[:3], indent=2)}
Recommended actions: {json.dumps(next_actions[:3], indent=2)}
Stakeholders: {json.dumps(stakeholders[:5], indent=2)}

{f'<meeting_context>{_html.escape(meeting_context)}</meeting_context>' if meeting_context else ''}

Format rules:
- No em-dashes (use a comma or a new sentence instead)
- No AI-sounding words (no "leverage", "synergies", "robust", "seamlessly", "game-changer", "it is worth noting")
- Use short bullet points under each section header, not prose paragraphs
- One blank line between sections
- Plain, direct language a sales rep would actually say

Return the brief with these five sections:

**Deal status**
One sentence.

**Top risks to close**
- Risk 1
- Risk 2
- Risk 3

**Questions to ask**
- Question 1
- Question 2
- Question 3

**Recommended ask**
One sentence.

**Stakeholders**
- Name: role, sentiment"""

        response = await self._anthropic.messages.create(
            model=self.settings.anthropic_model_quality,
            max_tokens=1500,
            system=_build_system_prompt(seller_context),
            messages=[{"role": "user", "content": prompt}],
        )

        brief_text = strip_dashes(response.content[0].text)

        return {
            "account_name": account.name,
            "stage": account.stage,
            "deal_amount": float(account.deal_amount) if account.deal_amount else None,
            "ai_forecast": pov.get("forecast_category"),
            "ai_confidence": pov.get("confidence"),
            "health_score": account.health_score,
            "top_signals": signals[:3],
            "next_actions": next_actions[:3],
            "stakeholders": stakeholders[:5],
            "brief": brief_text,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    async def list_threads(
        self,
        user_id: str,
        workspace_id: str,
        account_id: Optional[str] = None,
        page: int = 1,
        limit: int = 20,
    ) -> list[dict]:
        """List conversation threads for a user."""
        try:
            # IMPORTANT: `filters` is built ONLY from hard-coded string literals and parameterized
            # placeholders. Never interpolate user-supplied values directly into this string.
            filters = "WHERE user_id = :user_id AND workspace_id = :workspace_id"
            params = {"user_id": user_id, "workspace_id": workspace_id}
            if account_id:
                if not _is_valid_uuid(account_id):
                    return []
                filters += " AND account_id = :account_id"
                params["account_id"] = account_id

            result = await self.db.execute(
                text(f"""
                    SELECT id, account_id, updated_at,
                           jsonb_array_length(messages) AS message_count,
                           messages->-1->>'content' AS last_message
                    FROM conversations
                    {filters}
                    ORDER BY updated_at DESC
                    LIMIT :limit OFFSET :offset
                """),
                {**params, "limit": limit, "offset": (page - 1) * limit},
            )
            rows = result.fetchall()
            return [
                {
                    "thread_id": str(row.id),
                    "account_id": row.account_id,
                    "message_count": row.message_count,
                    "last_message": (row.last_message or "")[:100],
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                }
                for row in rows
            ]
        except Exception as e:
            log.warning("list_threads_failed", error=str(e))
            return []

    async def get_thread(
        self,
        thread_id: str,
        user_id: str,
        workspace_id: str,
    ) -> Optional[list[dict]]:
        """Return full message history for a thread."""
        try:
            result = await self.db.execute(
                text("SELECT messages FROM conversations WHERE id = :id AND user_id = :user_id AND workspace_id = :ws"),
                self._owned_thread_params(thread_id, user_id, workspace_id),
            )
            row = result.fetchone()
            return row.messages if row else None
        except Exception as e:
            log.warning("get_thread_failed", thread_id=thread_id, error=str(e))
            return None

    async def delete_thread(self, thread_id: str, user_id: str, workspace_id: str) -> bool:
        """Delete a conversation thread."""
        try:
            result = await self.db.execute(
                text("DELETE FROM conversations WHERE id = :id AND user_id = :user_id AND workspace_id = :ws RETURNING id"),
                self._owned_thread_params(thread_id, user_id, workspace_id),
            )
            await self.db.commit()
            return result.rowcount > 0
        except Exception as e:
            log.warning("delete_thread_failed", thread_id=thread_id, error=str(e))
            return False

    # ── Private helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _owned_thread_params(thread_id: str, user_id: str, workspace_id: str) -> dict:
        """Return the param dict for the ownership-guard WHERE clause used in get/delete."""
        return {"id": thread_id, "user_id": user_id, "ws": workspace_id}

    async def _build_messages(
        self,
        history: list[dict],
        message: str,
        account: Optional[Account],
        use_perplexity: bool,
    ) -> list[dict]:
        """Assemble the messages list for the Claude API call.

        Optionally appends a <web_research> block when Perplexity returns data —
        kept separate from the system prompt so it counts as user-turn grounding.
        """
        perplexity_context = ""
        if use_perplexity and account and self.settings.perplexity_api_key:
            try:
                perp = PerplexityClient(self.settings.perplexity_api_key)
                perplexity_context = await perp.answer_question(
                    question=message,
                    context=f"Account: {account.name}. Question context: sales intelligence query.",
                )
            except Exception as e:
                log.warning("perplexity_assistant_error", error=str(e))

        user_content = message
        if perplexity_context:
            user_content += f"\n\n<web_research>\n{_html.escape(perplexity_context)}\n</web_research>"

        return [*history, {"role": "user", "content": user_content}]

    # _build_context is the live fallback (cache miss path).  The pre-compressed Redis variant
    # (fast path) is built inline in nightly_worker.py and stored via cache_compressed_context.
    def _build_context(self, account: Optional[Account]) -> str:
        """Build a concise context string from the account ASO for the system prompt."""
        if not account:
            return ""

        state = account.state or {}
        pov = state.get("pov", {})
        signals = state.get("signals", [])
        gold_data = state.get("gold_data", {})
        episodic = state.get("episodic_memory", {})

        _deal_amt = _fmt_amount(account.deal_amount)
        parts = [
            f"### {account.name}",
            f"Stage: {account.stage} | Amount: {_deal_amt} | Close: {account.close_date}",
            f"Health: {account.health_score or '?'}/1.0 | Urgency: {account.urgency_score or '?'}/1.0",
            f"AI POV: {pov.get('forecast_category', 'Unknown')} ({pov.get('forecast_confidence') or 0:.0%})",
        ]

        if pov.get("risks"):
            parts.append(f"Risks: {', '.join(_risk_text(r)[:80] for r in pov['risks'][:3])}")

        if signals:
            parts.append("Signals:")
            for sig in signals[:5]:
                parts.append(f"  [{sig.get('urgency', '?')}] {sig.get('detail', '')[:120]} (source: {sig.get('source', '?')})")

        if gold_data:
            parts.append(f"Gold Data: {len(gold_data)} verified facts")

        summary = episodic.get("summary", "")
        if summary:
            parts.append(f"History: {summary[:400]}")

        return "\n".join(parts)

    async def _build_workspace_context(self, workspace_id: str) -> str:
        """
        Build portfolio-level context when the chat is not scoped to one account.
        Queries top 20 accounts by urgency so the assistant can answer cross-portfolio
        questions like "which deals are most at risk this quarter".
        """
        try:
            result = await self.db.execute(
                select(Account)
                .where(
                    Account.workspace_id == workspace_id,
                    Account.deleted_at.is_(None),
                )
                .order_by(
                    Account.urgency_score.desc().nullslast(),
                    Account.last_agent_run_at.desc().nullslast(),
                )
                .limit(20)
            )
            accounts = result.scalars().all()

            if not accounts:
                return "No accounts in this workspace yet. Connect HubSpot and sync deals to get started."

            total_value = sum(float(a.deal_amount or 0) for a in accounts)
            analyzed = sum(1 for a in accounts if a.last_agent_run_at)

            parts = [
                f"## Pipeline ({len(accounts)} accounts shown, ${total_value:,.0f} total value)",
                f"{analyzed} analyzed by agent pipeline. {len(accounts) - analyzed} not yet processed.",
                "",
            ]

            for a in accounts:
                state = a.state or {}
                pov = state.get("pov", {})
                signals = state.get("signals", [])

                stage = a.stage or "Unknown Stage"
                amt = _fmt_amount(a.deal_amount, fallback="No amount")
                close = str(a.close_date) if a.close_date else "No close date"

                forecast = pov.get("forecast_category")
                segments = [
                    f"- **{a.name}**", stage, amt, f"Close: {close}",
                    f"Health: {a.health_score:.0%}" if a.health_score is not None else None,
                    f"Urgency: {a.urgency_score:.0%}" if a.urgency_score is not None else None,
                    f"AI: {forecast}" if forecast else None,
                ]
                parts.append(" | ".join(s for s in segments if s is not None))

                # Top risk sub-bullet
                risks = pov.get("risks", [])
                if risks:
                    risk_text = _risk_text(risks[0])
                    if risk_text:
                        parts.append(f"  Risk: {risk_text[:160]}")

                # Top signal sub-bullet
                if signals:
                    sig = signals[0]
                    urgency_label = (sig.get("urgency") or "?").upper()
                    parts.append(f"  Signal: [{urgency_label}] {sig.get('detail', '')[:120]}")

            parts.append("")
            parts.append("When answering, name the specific account and cite the data point you're using.")
            return "\n".join(parts)

        except Exception as e:
            log.warning("workspace_context_failed", error=str(e))
            return ""

    def _extract_citations(self, response_text: str, account: Optional[Account]) -> list[dict]:
        """
        Extract citation markers from response text and resolve to Gold Data.
        Format: [Source, Date] in the text.
        """
        citations = []
        # Known false-positive risk: the pattern matches any [foo, bar] bracket pair, including
        # markdown list items with commas.  Accepted trade-off — over-citation is preferable to
        # missing real Gold Data references at current volume.
        pattern = r'\[([^\]]+),\s*([^\]]+)\]'
        matches = re.findall(pattern, response_text)

        state = account.state or {} if account else {}
        gold_data = state.get("gold_data", {})

        for source, qualifier in matches:
            # `qualifier` is the second bracket group — typically a date but may be any label
            citations.append({
                "source": source.strip(),
                "date": qualifier.strip(),
                "gold_data": gold_data.get(source.strip(), {}),
            })

        return citations

    async def _get_thread_messages(self, thread_id: str, user_id: str, workspace_id: str) -> list[dict]:
        """Load thread message history (last 20 messages for context window)."""
        messages = await self.get_thread(thread_id, user_id, workspace_id)
        if not messages:
            return []
        # Cap each message at 2,000 chars to prevent prompt injection from long history.
        # 20-message window keeps token cost bounded (~40k chars max) while covering a
        # full back-and-forth session; older turns are already persisted in the DB.
        history = messages[-20:]
        return [
            {**m, "content": m["content"][:2000]} if isinstance(m.get("content"), str) else m
            for m in history
        ]

    async def _save_thread(
        self,
        thread_id: str,
        user_id: str,
        workspace_id: str,
        account_id: Optional[str],
        messages: list[dict],
    ) -> None:
        """Upsert thread history."""
        try:
            await self.db.execute(
                text("""
                    INSERT INTO conversations (id, user_id, workspace_id, account_id, messages, created_at, updated_at)
                    VALUES (:id, :user_id, :workspace_id, :account_id, CAST(:messages AS jsonb), NOW(), NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET messages = CAST(:messages AS jsonb), updated_at = NOW()
                """),
                {
                    "id": thread_id,
                    "user_id": user_id,
                    "workspace_id": workspace_id,
                    "account_id": account_id,
                    "messages": json.dumps(messages),
                },
            )
            await self.db.commit()
            log.info("thread_saved", thread_id=thread_id, message_count=len(messages))
        except Exception as e:
            log.warning("thread_save_failed", thread_id=thread_id, error=str(e))
