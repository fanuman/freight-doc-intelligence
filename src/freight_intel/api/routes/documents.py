"""HTTP layer for documents: parse the request, call a service, map errors to status codes."""
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request, Response, UploadFile, status

from freight_intel.api.deps import CurrentUserDep, LLMDep, SaverDep, StorageDep
from freight_intel.config import get_settings
from freight_intel.schemas.documents import (
    DocumentDetail, DocumentSummary, ReconcileResponse, ReviewRequest, ReviewResponse, UploadResponse,
)
from freight_intel.services import documents as documents_service
from freight_intel.services import processing
from freight_intel.services.uploads import UploadRejected, check_upload

router = APIRouter(prefix="/documents", tags=["documents"])

MULTIPART_OVERHEAD = 64 * 1024  # a multipart body is a little larger than the file inside it
UPLOAD_STATUS = {"too_large": 413, "unsupported_type": 415}  # every other rejection is a 422


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")


@router.post("", response_model=UploadResponse, status_code=status.HTTP_202_ACCEPTED)
def upload_document(
    request: Request, response: Response, file: UploadFile, background: BackgroundTasks,
    user: CurrentUserDep, llm: LLMDep, saver: SaverDep, storage: StorageDep,
) -> UploadResponse:
    """Accept a file, answer 202 at once, and read it in the background. Poll GET /documents/{id} for the result."""
    limit = get_settings().max_upload_bytes
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit + MULTIPART_OVERHEAD:
        raise HTTPException(413, "File is too large")
    data = file.file.read(limit + 1)  # one byte more than allowed, so "too large" can be told from "exactly the limit"
    try:
        checked = check_upload(file.filename, data, max_bytes=limit)
    except UploadRejected as exc:
        raise HTTPException(UPLOAD_STATUS.get(exc.code, 422), exc.message)

    document_id = documents_service.register_upload(
        tenant_id=user.tenant_id, user_id=user.user_id, upload=checked, storage=storage
    )
    background.add_task(
        processing.process_document,
        tenant_id=user.tenant_id, document_id=document_id, llm=llm, checkpointer=saver, storage=storage,
    )
    response.headers["Location"] = f"/documents/{document_id}"
    return UploadResponse(id=document_id, status="uploaded")


@router.get("", response_model=list[DocumentSummary])
def list_documents(
    user: CurrentUserDep, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)
) -> list[dict]:
    return documents_service.list_documents(tenant_id=user.tenant_id, limit=limit, offset=offset)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, user: CurrentUserDep, saver: SaverDep) -> dict:
    try:
        return documents_service.get_document(tenant_id=user.tenant_id, document_id=document_id, checkpointer=saver)
    except documents_service.DocumentNotFound:
        raise _not_found()


@router.post("/{document_id}/review", response_model=ReviewResponse)
def review_document(document_id: uuid.UUID, body: ReviewRequest, user: CurrentUserDep, saver: SaverDep) -> ReviewResponse:
    """Answer a document that is waiting for a person: approve it, correct it, or reject it."""
    try:
        outcome = processing.submit_review(
            tenant_id=user.tenant_id, user_id=user.user_id, document_id=document_id,
            decision=body.model_dump(), checkpointer=saver,
        )
    except processing.DocumentNotFound:
        raise _not_found()
    except processing.NotAwaitingReview:
        raise HTTPException(status.HTTP_409_CONFLICT, "This document is not waiting for a review")
    except processing.InvalidDecision as exc:
        raise HTTPException(422, str(exc))
    if not outcome.accepted:  # e.g. an approval over errors without a note; nothing was saved
        raise HTTPException(422, outcome.question["error"])
    return ReviewResponse(document_status=outcome.document_status, question=outcome.question)


@router.post("/{document_id}/reconcile", response_model=ReconcileResponse)
def reconcile_document(document_id: uuid.UUID, user: CurrentUserDep) -> ReconcileResponse:
    """Compare an invoice with its quote. Not finding exactly one safe quote is an outcome, not an error."""
    try:
        outcome = documents_service.reconcile_document(tenant_id=user.tenant_id, document_id=document_id)
    except documents_service.DocumentNotFound:
        raise _not_found()
    except documents_service.NotReconcilable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return ReconcileResponse(
        status=outcome.status, reconciliation_id=outcome.reconciliation_id, discrepancy_count=outcome.discrepancy_count
    )
