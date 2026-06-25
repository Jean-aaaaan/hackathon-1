"""
Document model — generated sales collateral (proposals, decks, battle cards, etc.)
"""
import uuid
from sqlalchemy import (
    Column, String, Text, DateTime, Float, Integer, LargeBinary,
    ForeignKey, func, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.database import Base


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), nullable=False)
    account_id = Column(UUID(as_uuid=True), ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)

    doc_type = Column(Text, nullable=False)
    # proposal | sales_deck | battle_card | business_case | roi_calculator | mutual_action_plan

    status = Column(Text, nullable=False, default="generating")
    # generating | ready | failed

    title = Column(Text, nullable=False)
    file_name = Column(Text, nullable=False)
    file_format = Column(Text, nullable=False)  # docx | pptx
    file_size_bytes = Column(Integer)
    file_data = Column(LargeBinary)             # stored in DB for MVP

    generated_by = Column(Text, default="user_request")  # user_request | nightly_agent

    generation_context = Column(JSONB, default={})
    # {signals_used: int, transcripts_used: int, gold_data_keys: [...]}

    grounding_confidence = Column(Float)        # inherited from account grounding score
    error_message = Column(Text)               # set on failure

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_documents_account_id", "account_id"),
        Index("ix_documents_workspace_id", "workspace_id"),
    )
