"""
AccountService — Core data access layer for accounts.
Handles list/filter/search with pgvector semantic similarity.
"""
from typing import Optional, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, text
from sqlalchemy.orm import selectinload
import structlog

from app.models.account import Account, Draft, Signal
from app.integrations.anthropic_embed import get_embedding

log = structlog.get_logger()


class AccountService:
    """Data access layer for account queries."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_accounts(
        self,
        workspace_id: str,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "urgency_score",
        sort_dir: str = "desc",
        stage: Optional[str] = None,
        owner_id: Optional[str] = None,
        min_urgency: Optional[float] = None,
        min_amount: Optional[float] = None,
        close_before: Optional[str] = None,   # ISO date string YYYY-MM-DD
        has_pending_drafts: Optional[bool] = None,
    ) -> Tuple[list[Account], int]:
        """
        List accounts with filtering and pagination.
        Eager-loads drafts for pending_drafts count.
        """
        from datetime import date as date_type
        base_q = (
            select(Account)
            .where(
                Account.workspace_id == workspace_id,
                Account.deleted_at.is_(None),
            )
            .options(selectinload(Account.drafts))
        )

        # Apply filters
        if stage:
            base_q = base_q.where(Account.stage == stage)
        if owner_id:
            base_q = base_q.where(Account.owner_rep_id == owner_id)
        if min_urgency is not None:
            base_q = base_q.where(Account.urgency_score >= min_urgency)
        if min_amount is not None:
            base_q = base_q.where(Account.deal_amount >= min_amount)
        if close_before is not None:
            try:
                cb = date_type.fromisoformat(close_before)
                base_q = base_q.where(Account.close_date <= cb, Account.close_date.is_not(None))
            except ValueError:
                pass  # ignore invalid date strings
        if has_pending_drafts is True:
            # Join to drafts and require at least one pending
            base_q = base_q.join(Draft, and_(
                Draft.account_id == Account.id,
                Draft.status == "pending",
            )).distinct()

        # Count total (before pagination)
        count_q = select(func.count()).select_from(base_q.subquery())
        total_result = await self.db.execute(count_q)
        total = total_result.scalar_one()

        # Apply sort
        sort_col = getattr(Account, sort_by, Account.urgency_score)
        if sort_dir == "desc":
            base_q = base_q.order_by(sort_col.desc().nullslast())
        else:
            base_q = base_q.order_by(sort_col.asc().nullsfirst())

        # Apply pagination
        offset = (page - 1) * limit
        base_q = base_q.offset(offset).limit(limit)

        result = await self.db.execute(base_q)
        accounts = result.scalars().all()

        return list(accounts), total

    async def get_account(
        self,
        account_id: str,
        workspace_id: str,
        owner_rep_id: Optional[str] = None,
    ) -> Optional[Account]:
        """
        Fetch a single account with all relations.
        Pass owner_rep_id for non-managers to enforce rep-level isolation.
        """
        import uuid as _uuid
        try:
            _acct_uuid = _uuid.UUID(account_id)
        except (ValueError, AttributeError):
            return None

        q = (
            select(Account)
            .where(
                Account.id == _acct_uuid,
                Account.workspace_id == workspace_id,
                Account.deleted_at.is_(None),
            )
            .options(
                selectinload(Account.drafts),
                selectinload(Account.signals),
            )
        )
        if owner_rep_id:
            q = q.where(Account.owner_rep_id == owner_rep_id)

        result = await self.db.execute(q)
        return result.scalar_one_or_none()

    async def semantic_search(
        self,
        workspace_id: str,
        query: str,
        limit: int = 10,
        min_urgency: Optional[float] = None,
        stage: Optional[str] = None,
    ) -> list[dict]:
        """
        Semantic similarity search across accounts using pgvector.
        Embeds the query and finds nearest neighbors by cosine similarity.
        Returns accounts ranked by similarity × urgency boost.
        All filter values are parameterized — no string interpolation.
        """
        # Embed the query — fall back to name-based text search when embeddings unavailable
        query_embedding = await get_embedding(query)
        if not query_embedding:
            log.warning("semantic_search_embed_failed", query=query[:50])
            return await self._text_search(workspace_id, query, limit, min_urgency, stage)



        # Build parameterized conditions
        conditions = [
            "workspace_id = :ws",
            "deleted_at IS NULL",
            "embedding IS NOT NULL",
        ]
        params: dict = {"ws": workspace_id, "embedding": str(query_embedding), "limit": limit}

        if min_urgency is not None:
            conditions.append("urgency_score >= :min_urgency")
            params["min_urgency"] = min_urgency
        if stage:
            conditions.append("stage = :stage")
            params["stage"] = stage

        where_clause = " AND ".join(conditions)

        # pgvector cosine similarity — <=> = cosine distance (1 - similarity)
        # Boost by urgency so urgent + relevant accounts surface first
        # workspace_id, stage, min_urgency are parameterized — not interpolated
        sql = text(f"""
            SELECT
                id::text,
                name,
                stage,
                deal_amount,
                health_score,
                urgency_score,
                pov_forecast_cat,
                pov_confidence,
                last_agent_run_at,
                1 - (embedding <=> :embedding) AS similarity,
                (1 - (embedding <=> :embedding)) * (0.5 + COALESCE(urgency_score, 0) * 0.5) AS relevance_score
            FROM accounts
            WHERE {where_clause}
            ORDER BY relevance_score DESC
            LIMIT :limit
        """)

        result = await self.db.execute(sql, params)
        rows = result.fetchall()

        return [
            {
                "id": row.id,
                "name": row.name,
                "stage": row.stage,
                "deal_amount": float(row.deal_amount) if row.deal_amount else None,
                "health_score": row.health_score,
                "urgency_score": row.urgency_score,
                "pov_forecast_cat": row.pov_forecast_cat,
                "pov_confidence": row.pov_confidence,
                "last_agent_run_at": row.last_agent_run_at.isoformat() if row.last_agent_run_at else None,
                "similarity": round(float(row.similarity), 4),
                "relevance_score": round(float(row.relevance_score), 4),
            }
            for row in rows
        ]

    async def _text_search(
        self,
        workspace_id: str,
        query: str,
        limit: int,
        min_urgency: Optional[float],
        stage: Optional[str],
    ) -> list[dict]:
        """Name-based ILIKE fallback when embeddings are unavailable."""
        conditions = [
            "workspace_id = :ws",
            "deleted_at IS NULL",
            "name ILIKE :pattern",
        ]
        params: dict = {"ws": workspace_id, "pattern": f"%{query}%", "limit": limit}
        if min_urgency is not None:
            conditions.append("urgency_score >= :min_urgency")
            params["min_urgency"] = min_urgency
        if stage:
            conditions.append("stage = :stage")
            params["stage"] = stage

        sql = text(f"""
            SELECT id::text, name, stage, deal_amount, health_score, urgency_score,
                   pov_forecast_cat, pov_confidence, last_agent_run_at,
                   1.0 AS similarity,
                   COALESCE(urgency_score, 0) AS relevance_score
            FROM accounts
            WHERE {' AND '.join(conditions)}
            ORDER BY urgency_score DESC NULLS LAST
            LIMIT :limit
        """)
        result = await self.db.execute(sql, params)
        rows = result.fetchall()
        return [
            {
                "id": row.id,
                "name": row.name,
                "stage": row.stage,
                "deal_amount": float(row.deal_amount) if row.deal_amount else None,
                "health_score": row.health_score,
                "urgency_score": row.urgency_score,
                "pov_forecast_cat": row.pov_forecast_cat,
                "pov_confidence": row.pov_confidence,
                "last_agent_run_at": row.last_agent_run_at.isoformat() if row.last_agent_run_at else None,
                "similarity": 1.0,
                "relevance_score": round(float(row.urgency_score or 0), 4),
            }
            for row in rows
        ]

    async def get_account_by_hubspot_id(
        self,
        hubspot_deal_id: str,
        workspace_id: str,
    ) -> Optional[Account]:
        """Fetch account by HubSpot deal ID (used in webhook handler)."""
        result = await self.db.execute(
            select(Account).where(
                Account.hubspot_deal_id == hubspot_deal_id,
                Account.workspace_id == workspace_id,
                Account.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_accounts_for_batch(
        self,
        workspace_id: str,
        account_ids: Optional[list[str]] = None,
        min_urgency: Optional[float] = None,
        stage_filter: Optional[str] = None,
    ) -> list[Account]:
        """Fetch accounts for batch agent run."""
        q = select(Account).where(
            Account.workspace_id == workspace_id,
            Account.deleted_at.is_(None),
        )

        if account_ids:
            q = q.where(Account.id.in_(account_ids))
        if min_urgency is not None:
            q = q.where(Account.urgency_score >= min_urgency)
        if stage_filter and not account_ids:
            _safe_stage = stage_filter.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q = q.where(Account.stage.ilike(f"%{_safe_stage}%", escape="\\"))

        # Prioritise by urgency so high-urgency accounts run first
        q = q.order_by(Account.urgency_score.desc().nullslast())

        # Cap at 50 rows at the DB level — callers further restrict via MANUAL_RUN_LIMIT
        q = q.limit(50)

        result = await self.db.execute(q)
        return list(result.scalars().all())
