"""Clean LLM artifact stakeholder names in account state.

Researcher output sometimes stored sentence fragments as stakeholder names
("Only Derick Sim"), which the UI displayed as separate people. Strip the
leading artifact word and dedupe by the normalized name (keeping the first
occurrence). The orchestrator now self-heals on every run; this fixes
accounts that won't run again (closed stages).

Revision ID: 20260610_0013
Revises: 20260610_0012
Create Date: 2026-06-10
"""
from alembic import op

revision = '20260610_0013'
down_revision = '20260610_0012'
branch_labels = None
depends_on = None

_PREFIX = r"'^(only|the|both|either|all|new|unknown|possibly|likely|maybe)\s+'"


def upgrade() -> None:
    op.execute(
        f"""
        UPDATE accounts SET state = jsonb_set(state, '{{stakeholders}}', (
            SELECT COALESCE(jsonb_agg(cleaned ORDER BY ord), '[]'::jsonb)
            FROM (
                SELECT DISTINCT ON (lower(regexp_replace(s->>'name', {_PREFIX}, '', 'i')))
                    jsonb_set(
                        s, '{{name}}',
                        to_jsonb(regexp_replace(s->>'name', {_PREFIX}, '', 'i'))
                    ) AS cleaned,
                    ord
                FROM jsonb_array_elements(state->'stakeholders') WITH ORDINALITY AS t(s, ord)
                WHERE s->>'name' IS NOT NULL AND trim(s->>'name') != ''
                ORDER BY lower(regexp_replace(s->>'name', {_PREFIX}, '', 'i')), ord
            ) deduped
        ))
        WHERE jsonb_typeof(state->'stakeholders') = 'array'
          AND jsonb_array_length(state->'stakeholders') > 0
        """
    )


def downgrade() -> None:
    # Data cleanup — original artifact entries are not recoverable.
    pass
