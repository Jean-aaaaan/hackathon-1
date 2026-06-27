"""
Fireflies webhook router — receives transcript.ready events.
POST /webhooks/fireflies

When Fireflies finishes processing a call, it POSTs here.
We immediately ingest the transcript into episodic memory for the matched account.
"""
import hashlib
import hmac
from fastapi import APIRouter, Request, HTTPException, Header, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import structlog

from app.db.database import get_db
from app.config import get_settings
from app.integrations.fireflies import FirefliesClient, transcript_to_interaction
from app.models.account import Interaction, AuditLog
from app.middleware.auth import get_current_user

log = structlog.get_logger()
router = APIRouter()


def _verify_fireflies_sig(body: bytes, signature: str, secret: str) -> bool:
    """Verify Fireflies HMAC-SHA256 webhook signature."""
    if not secret:
        return False  # Never accept without a configured secret
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature or "")


@router.post("/fireflies")
async def fireflies_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_fireflies_signature: str = Header(None, alias="X-Fireflies-Signature"),
):
    """
    Receive Fireflies transcript.ready webhook.
    Matches the transcript to an account by title/participant domain,
    then inserts an Interaction record for episodic memory.
    """
    settings = get_settings()
    body = await request.body()

    # Signature verification — always required if Fireflies is configured
    if not settings.fireflies_webhook_secret:
        log.error("fireflies_webhook_secret_not_configured")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    if not _verify_fireflies_sig(body, x_fireflies_signature or "", settings.fireflies_webhook_secret):
        log.warning("fireflies_webhook_signature_invalid", has_header=bool(x_fireflies_signature))
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event_type = payload.get("eventType", "")
    meeting_id = payload.get("meetingId") or payload.get("id")

    log.info("fireflies_webhook_received", event_type=event_type, meeting_id=meeting_id)

    # Only process transcript.ready events
    if event_type not in ("Transcription completed", "transcript.ready", "TRANSCRIPTION_COMPLETE"):
        return Response(status_code=204)

    if not meeting_id:
        return Response(status_code=204)

    # Fetch full transcript from Fireflies
    client = FirefliesClient(api_key=settings.fireflies_api_key)
    transcript = await client.get_transcript_by_id(meeting_id)

    if not transcript:
        log.warning("fireflies_transcript_not_found", meeting_id=meeting_id)
        return Response(status_code=204)

    # Try to match transcript to an account by title
    raw_title = transcript.get("title", "") or ""
    # Sanitize: strip control characters, limit length
    title = "".join(c for c in raw_title if c.isprintable())[:500].lower()

    if not title:
        return Response(status_code=204)

    # Reject if title contains SQL injection patterns
    _sql_patterns = ("drop ", "delete ", "insert ", "update ", "union ", "exec ", "select ", "--", ";")
    if any(p in title.lower() for p in _sql_patterns):
        log.warning("fireflies_suspicious_title", title=title[:100])
        return Response(status_code=204)

    # Require title to be at least 5 chars AND have ≥2 tokens of ≥5 chars each
    # to avoid overly broad fuzzy matches on generic words like "meeting" or "call"
    if len(title) < 5:
        log.info("fireflies_title_too_short", title_len=len(title))
        return Response(status_code=204)
    _specific_tokens = [t for t in title.split() if len(t) >= 5]
    if len(_specific_tokens) < 2:
        log.info("fireflies_title_insufficient_specificity", title=title[:100])
        return Response(status_code=204)

    # Scope search to the workspace associated with the configured Fireflies integration.
    # Multi-workspace deployments each need a separate Fireflies webhook URL + secret pair;
    # for now, all Fireflies events are scoped to the default workspace.
    from app.models.account import Account as _Account
    import uuid as _uuid
    _ws_id = settings.default_workspace_id
    if not _ws_id:
        log.warning("fireflies_no_default_workspace_configured")
        return Response(status_code=204)

    # Escape LIKE wildcards in the Fireflies-supplied title before pattern matching
    _safe_title = title[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    title_pattern = f"%{_safe_title}%"
    acct_result = await db.execute(
        select(_Account.id, _Account.name, _Account.workspace_id)
        .where(
            _Account.workspace_id == _uuid.UUID(_ws_id),
            _Account.deleted_at.is_(None),
            _Account.name.ilike(title_pattern, escape="\\"),
        )
        .limit(1)
    )
    matched_accounts = acct_result.fetchall()

    if not matched_accounts:
        log.info("fireflies_no_account_match", title=title)
        return Response(status_code=204)

    # Insert Interaction for each matched account
    interaction_data = transcript_to_interaction(transcript)
    # Dedup marker: the old check compared Interaction.outcome to the meeting id,
    # but outcome stores action-item text — it never matched and every re-delivery
    # duplicated the call. Tag notes with the meeting id and match on that.
    _dedup_marker = f"[ff:{meeting_id}]"
    marked_notes = f"{_dedup_marker}\n{interaction_data['notes']}"

    from datetime import datetime, timezone
    for account_row in matched_accounts:
        account_id = str(account_row.id)

        # Deduplication: skip if this transcript was already ingested for this account.
        # Cast account_id to UUID — ORM column is UUID type; a raw string silently
        # never matches on some asyncpg versions, letting every redelivery duplicate.
        dup_check = await db.execute(
            select(Interaction).where(
                Interaction.account_id == _uuid.UUID(account_id),
                Interaction.source == "fireflies",
                Interaction.notes.like(f"{_dedup_marker}%"),
            ).limit(1)
        )
        if dup_check.scalar_one_or_none():
            log.info("fireflies_duplicate_skipped", meeting_id=meeting_id, account_id=account_id)
            continue

        interaction = Interaction(
            account_id=account_id,
            workspace_id=account_row.workspace_id,
            type=interaction_data["type"],
            notes=marked_notes,
            outcome=interaction_data.get("outcome"),
            source=interaction_data["source"],
            occurred_at=datetime.fromisoformat(interaction_data["occurred_at"]) if interaction_data.get("occurred_at") else datetime.now(timezone.utc),
            is_training_signal=False,
        )
        db.add(interaction)

        # Audit log
        audit = AuditLog(
            workspace_id=str(account_row.workspace_id),
            actor_id="fireflies",
            action="fireflies_transcript_ingested",
            resource_type="interaction",
            resource_id=account_id,
            new_value={"fireflies_id": meeting_id, "title": transcript.get("title")},
        )
        db.add(audit)

        log.info(
            "fireflies_interaction_saved",
            account_id=account_id,
            account_name=account_row.name,
            meeting_id=meeting_id,
        )

    # Extract action items → create TimelineActions for matched accounts
    action_items: list[str] = []
    try:
        ai_data = transcript.get("summary") or {}
        raw_items = ai_data.get("action_items") or transcript.get("action_items") or []
        if isinstance(raw_items, list):
            action_items = [str(i).strip() for i in raw_items if i and str(i).strip()]
        elif isinstance(raw_items, str) and raw_items.strip():
            action_items = [ln.strip("•- ").strip() for ln in raw_items.split("\n") if ln.strip()]
    except Exception:
        pass

    if action_items:
        from app.services.timeline_service import TimelineService
        from app.models.account import Account as _AccModel
        tl_service = TimelineService(db)
        transcript_dt = datetime.now(timezone.utc)
        try:
            raw_date = transcript.get("date", 0)
            if raw_date:
                transcript_dt = datetime.fromtimestamp(int(raw_date) / 1000, tz=timezone.utc)
        except Exception:
            pass

        for account_row in matched_accounts:
            try:
                acc_result = await db.execute(
                    select(_AccModel).where(_AccModel.id == account_row.id)
                )
                account_obj = acc_result.scalar_one_or_none()
                if account_obj:
                    tl_count = await tl_service.create_from_fireflies(
                        account_obj, action_items, transcript_dt, meeting_id
                    )
                    if tl_count:
                        log.info("timeline_actions_from_fireflies",
                                 account_id=str(account_row.id), count=tl_count)
            except Exception as e:
                log.warning("timeline_from_fireflies_failed",
                            account_id=str(account_row.id), error=str(e))

    # Merge the canonical transcript entry into each account's state so the
    # War Room / Deal Book see the call (with talk-time, buyer questions,
    # commitments) immediately — not only after the next nightly run.
    try:
        from sqlalchemy.orm.attributes import flag_modified
        from app.models.workspace import Workspace as _Workspace
        from app.services.conversation_intel import (
            build_transcript_entry, merge_transcript_entries, compute_conversation_rollup,
        )
        ws_row = await db.execute(select(_Workspace).where(_Workspace.id == _uuid.UUID(_ws_id)))
        ws = ws_row.scalar_one_or_none()
        seller_domains = set((ws.settings or {}).get("seller_domains", [])) if ws else set()
        entry = build_transcript_entry(transcript, seller_domains)
        for account_row in matched_accounts:
            acc_result = await db.execute(
                select(_Account).where(_Account.id == account_row.id)
            )
            account_obj = acc_result.scalar_one_or_none()
            if not account_obj:
                continue
            state = account_obj.state or {}
            state["transcripts"] = merge_transcript_entries(
                state.get("transcripts", []), [entry]
            )
            state["conversation_intel"] = compute_conversation_rollup(
                state["transcripts"], state.get("stakeholders", [])
            )
            account_obj.state = state
            flag_modified(account_obj, "state")
    except Exception as e:
        # State enrichment is additive — never fail the ingest over it
        log.warning("fireflies_state_merge_failed", meeting_id=meeting_id, error=str(e))

    await db.commit()
    return {"status": "ingested", "accounts_matched": len(matched_accounts)}
