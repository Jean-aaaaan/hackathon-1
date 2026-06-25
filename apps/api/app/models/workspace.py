"""
SQLAlchemy models — Workspace and WorkspaceUser
"""
from sqlalchemy import Column, String, Text, DateTime, Boolean, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
import uuid
from app.db.database import Base
from app.db.encrypted_type import EncryptedText


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    slug = Column(Text, nullable=False, unique=True)

    # HubSpot OAuth
    hubspot_portal_id = Column(Text)
    hubspot_access_token = Column(EncryptedText)
    hubspot_refresh_token = Column(EncryptedText)
    hubspot_token_expires_at = Column(DateTime(timezone=True))

    # Outlook (Microsoft Graph — for email send + read)
    outlook_access_token = Column(EncryptedText)
    outlook_refresh_token = Column(EncryptedText)
    outlook_token_expires_at = Column(DateTime(timezone=True))
    outlook_user_email = Column(Text)    # The mailbox being used for sending

    # Gong
    gong_workspace_id = Column(Text)
    gong_api_key = Column(EncryptedText)
    gong_access_token = Column(EncryptedText)

    # Enrichment
    perplexity_api_key = Column(EncryptedText)

    # Notifications
    slack_webhook_url = Column(EncryptedText)
    teams_webhook_url = Column(EncryptedText)

    # Billing (for future SaaS)
    stripe_customer_id = Column(Text)
    plan = Column(Text, default="internal")  # internal | starter | growth | enterprise

    # Settings (flexible JSONB)
    settings = Column(JSONB, default={})

    # Audit
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime(timezone=True))

    # Relationships
    users = relationship("WorkspaceUser", back_populates="workspace")
    accounts = relationship("Account", back_populates="workspace")


class WorkspaceUser(Base):
    __tablename__ = "workspace_users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workspace_id = Column(UUID(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    workos_user_id = Column(Text, nullable=False)
    email = Column(Text, nullable=False)
    name = Column(Text)
    role = Column(Text, default="rep")   # rep | manager | admin | owner
    hubspot_owner_id = Column(Text)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    workspace = relationship("Workspace", back_populates="users")
