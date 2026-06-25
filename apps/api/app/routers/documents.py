"""
Documents router — generated sales collateral.
GET  /v1/documents              — list docs for an account
POST /v1/documents/generate     — trigger async generation
GET  /v1/documents/{id}/download — binary download
DELETE /v1/documents/{id}       — soft delete
"""
import uuid
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db.database import get_db
from app.middleware.auth import get_current_user, CurrentUser
from app.models.document import Document
from app.models.account import Account
from app.services.document_generator import generate_document, FILE_FORMATS

log = structlog.get_logger()
router = APIRouter()


MIME_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class GenerateRequest(BaseModel):
    account_id: str
    doc_type: str  # proposal | sales_deck | battle_card | business_case | roi_calculator | mutual_action_plan


def _format_doc(d: Document) -> dict:
    fmt, label = FILE_FORMATS.get(d.doc_type, ("docx", d.doc_type.replace("_", " ").title()))
    return {
        "id": str(d.id),
        "account_id": str(d.account_id),
        "doc_type": d.doc_type,
        "status": d.status,
        "title": d.title,
        "file_name": d.file_name,
        "file_format": d.file_format,
        "file_size_bytes": d.file_size_bytes,
        "generated_by": d.generated_by,
        "generation_context": d.generation_context or {},
        "grounding_confidence": d.grounding_confidence,
        "error_message": d.error_message,
        "created_at": d.created_at.isoformat() if d.created_at else None,
    }


# ── Background task: do the actual generation ─────────────────────────────────

async def _run_generation(document_id: str, doc_type: str, account_id: str):
    """Runs in background — generates the document and updates DB record."""
    from app.db.database import AsyncSessionLocal as async_session_factory
    async with async_session_factory() as db:
        try:
            file_bytes = await generate_document(doc_type, account_id, db)

            # Fetch account for context
            acct = await db.get(Account, uuid.UUID(account_id))
            grounding = 0.0
            if acct and acct.state:
                pov = acct.state.get("pov") or {}
                grounding = pov.get("grounding_confidence") or 0.0

            # Update document record
            doc = await db.get(Document, uuid.UUID(document_id))
            if doc:
                doc.status = "ready"
                doc.file_data = file_bytes
                doc.file_size_bytes = len(file_bytes)
                doc.grounding_confidence = grounding
                doc.generation_context = {
                    "generated_at": datetime.now(timezone.utc).isoformat(),
                }
                await db.commit()
                log.info("document_generated", document_id=document_id, doc_type=doc_type,
                         size_bytes=len(file_bytes))

        except Exception as e:
            log.error("document_generation_failed", document_id=document_id,
                      doc_type=doc_type, error=str(e))
            try:
                doc = await db.get(Document, uuid.UUID(document_id))
                if doc:
                    doc.status = "failed"
                    doc.error_message = str(e)[:500]
                    await db.commit()
            except Exception:
                pass


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("")
async def list_documents(
    account_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all non-deleted documents for an account."""
    # Verify account belongs to this workspace
    acct = await db.execute(
        select(Account).where(
            Account.id == account_id,
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
    )
    if not acct.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Account not found")

    result = await db.execute(
        select(Document)
        .where(
            Document.account_id == account_id,
            Document.workspace_id == current_user.workspace_id,
            Document.deleted_at.is_(None),
        )
        .order_by(Document.created_at.desc())
    )
    docs = result.scalars().all()
    return {"data": [_format_doc(d) for d in docs]}


@router.post("/generate")
async def generate_document_endpoint(
    body: GenerateRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Trigger async document generation. Returns immediately with document_id.
    Poll GET /v1/documents?account_id= to check status.
    """
    valid_types = list(FILE_FORMATS.keys())
    if body.doc_type not in valid_types:
        raise HTTPException(
            status_code=422,
            detail=f"doc_type must be one of: {', '.join(valid_types)}"
        )

    # Verify account
    acct_result = await db.execute(
        select(Account).where(
            Account.id == body.account_id,
            Account.workspace_id == current_user.workspace_id,
            Account.deleted_at.is_(None),
        )
    )
    account = acct_result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")

    fmt, label = FILE_FORMATS[body.doc_type]
    safe_name = account.name.replace(" ", "_").replace("/", "-")[:40]
    today = datetime.now(timezone.utc).strftime("%Y%m%d")
    file_name = f"{label.replace(' ', '_')}_{safe_name}_{today}.{fmt}"

    doc = Document(
        id=uuid.uuid4(),
        workspace_id=uuid.UUID(current_user.workspace_id),
        account_id=uuid.UUID(body.account_id),
        doc_type=body.doc_type,
        status="generating",
        title=f"{label} — {account.name}",
        file_name=file_name,
        file_format=fmt,
        generated_by="user_request",
    )
    db.add(doc)
    await db.commit()

    document_id = str(doc.id)
    background_tasks.add_task(_run_generation, document_id, body.doc_type, body.account_id)

    log.info("document_generation_queued", document_id=document_id,
             doc_type=body.doc_type, account_id=body.account_id)

    return {
        "data": {
            "document_id": document_id,
            "status": "generating",
            "file_name": file_name,
            "message": f"Generating {label}. Poll GET /v1/documents?account_id={body.account_id} for status.",
        }
    }


@router.get("/{document_id}/download")
async def download_document(
    document_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a generated document as a binary file."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == current_user.workspace_id,
            Document.deleted_at.is_(None),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.status != "ready":
        raise HTTPException(
            status_code=409,
            detail=f"Document not ready (status: {doc.status})"
        )
    if not doc.file_data:
        raise HTTPException(status_code=500, detail="Document data missing")

    mime = MIME_TYPES.get(doc.file_format, "application/octet-stream")
    return Response(
        content=doc.file_data,
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{doc.file_name}"',
            "Content-Length": str(len(doc.file_data)),
        },
    )


@router.delete("/{document_id}")
async def delete_document(
    document_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete a document."""
    result = await db.execute(
        select(Document).where(
            Document.id == document_id,
            Document.workspace_id == current_user.workspace_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc.deleted_at = datetime.now(timezone.utc)
    await db.commit()
    return {"data": {"deleted": True, "document_id": document_id}}
