from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from datetime import datetime

from app.db.session import get_db
from app.models.freelancer import Freelancer
from freelance_api.dependencies import get_current_freelancer, mask_pan_or_aadhaar
from freelance_api.models import (
    FreelancerKycDocument,
    FreelancerKycSubmission,
    FreelancerFaceVerificationSession,
)
from freelance_api.schemas import (
    ApiResponse,
    KycDocumentResponse,
    KycSubmissionRequest,
    KycSubmissionResponse,
    KycStatusResponse,
    FaceVerificationStartRequest,
    FaceVerificationStartResponse,
    FaceVerificationStatusResponse,
    FaceVerificationWebhookPayload,
)
from freelance_api.service import FreelanceService

router = APIRouter(tags=["Freelancer KYC & Identity"])

@router.post("/freelancer/kyc/documents", response_model=ApiResponse[KycDocumentResponse], status_code=status.HTTP_201_CREATED)
async def upload_kyc_document(
    document_type: str = Form(..., description="aadhaar, pan, gst_certificate, address_proof"),
    document_number: Optional[str] = Form(None),
    file: UploadFile = File(...),
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Upload identity and address documents."""
    allowed_types = ("aadhaar", "pan", "gst_certificate", "address_proof")
    doc_type_clean = document_type.lower().strip()
    if doc_type_clean not in allowed_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid document type. Allowed: {', '.join(allowed_types)}"
        )

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File size exceeds 10MB limit")

    doc = await FreelanceService.submit_kyc_document(
        db=db,
        freelancer=current_freelancer,
        document_type=doc_type_clean,
        document_number=document_number,
        file_bytes=file_bytes,
        filename=file.filename or f"{doc_type_clean}.pdf",
        content_type=file.content_type or "application/octet-stream"
    )

    return ApiResponse(
        success=True,
        message="Document uploaded successfully",
        data=KycDocumentResponse(
            file_id=doc.id,
            document_type=doc.document_type,
            file_url=doc.file_url,
            upload_status="success",
            review_status=doc.status
        )
    )


@router.post("/freelancer/kyc/submissions", response_model=ApiResponse[KycSubmissionResponse], status_code=status.HTTP_201_CREATED)
async def submit_kyc(
    req: KycSubmissionRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Submit identity details and references to uploaded documents for review."""
    sub = await FreelanceService.submit_kyc_application(
        db=db,
        freelancer=current_freelancer,
        aadhaar=req.aadhaar_number,
        pan=req.pan_number,
        gst=req.gst_number,
        document_ids=req.document_ids
    )

    return ApiResponse(
        success=True,
        message="KYC application submitted for review",
        data=KycSubmissionResponse(
            submission_id=sub.submission_id,
            submitted_date=sub.submitted_at.isoformat() + "Z",
            kyc_status=sub.status,
            next_steps="Documents submitted. Verification typically takes 24-48 hours."
        )
    )


@router.get("/freelancer/kyc/status", response_model=ApiResponse[KycStatusResponse])
async def get_kyc_status(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Show current KYC and document verification status."""
    stmt_docs = select(FreelancerKycDocument).where(FreelancerKycDocument.freelancer_id == current_freelancer.id)
    res_docs = await db.execute(stmt_docs)
    docs = res_docs.scalars().all()

    doc_list = [
        {
            "id": d.id,
            "document_type": d.document_type,
            "masked_document_number": mask_pan_or_aadhaar(d.document_number),
            "status": d.status,
            "uploaded_at": d.created_at.isoformat() + "Z" if d.created_at else None,
            "rejection_reason": d.rejection_reason
        }
        for d in docs
    ]

    stmt_sub = select(FreelancerKycSubmission).where(
        FreelancerKycSubmission.freelancer_id == current_freelancer.id
    ).order_by(desc(FreelancerKycSubmission.submitted_at)).limit(1)
    res_sub = await db.execute(stmt_sub)
    latest_sub = res_sub.scalar_one_or_none()

    return ApiResponse(
        success=True,
        message="KYC status retrieved successfully",
        data=KycStatusResponse(
            overall_status=current_freelancer.kyc_status or "NOT_STARTED",
            document_statuses=doc_list,
            submission_date=latest_sub.submitted_at.isoformat() + "Z" if latest_sub else None,
            rejection_reason=latest_sub.rejection_reason if latest_sub else None
        )
    )


@router.post("/freelancer/kyc/face-verification", response_model=ApiResponse[FaceVerificationStartResponse])
async def start_face_verification(
    req: FaceVerificationStartRequest,
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Start face/liveness verification session."""
    session = await FreelanceService.start_face_verification(db, current_freelancer)
    return ApiResponse(
        success=True,
        message="Face verification session initiated",
        data=FaceVerificationStartResponse(
            verification_id=session.verification_id,
            session_token=session.session_token,
            status=session.status,
            provider=session.provider,
            sdk_config={
                "environment": "production",
                "captureMode": "passive_liveness",
                "timeoutSeconds": 300,
                "allowRetries": 3,
            }
        )
    )


@router.get("/freelancer/kyc/face-verification/status", response_model=ApiResponse[FaceVerificationStatusResponse])
async def get_face_verification_status(
    current_freelancer: Freelancer = Depends(get_current_freelancer),
    db: AsyncSession = Depends(get_db)
):
    """Get current status of face verification."""
    stmt = select(FreelancerFaceVerificationSession).where(
        FreelancerFaceVerificationSession.freelancer_id == current_freelancer.id
    ).order_by(desc(FreelancerFaceVerificationSession.created_at)).limit(1)
    res = await db.execute(stmt)
    session = res.scalar_one_or_none()

    if not session:
        return ApiResponse(
            success=True,
            message="No face verification session found",
            data=FaceVerificationStatusResponse(
                verification_id="",
                status="NOT_STARTED"
            )
        )

    return ApiResponse(
        success=True,
        message="Face verification status retrieved",
        data=FaceVerificationStatusResponse(
            verification_id=session.verification_id,
            status=session.status,
            verified_at=session.verified_at.isoformat() + "Z" if session.verified_at else None,
            failure_reason=session.failure_reason
        )
    )


@router.post("/freelancer/kyc/face-verification/webhook", response_model=ApiResponse[dict])
async def face_verification_webhook(payload: FaceVerificationWebhookPayload, db: AsyncSession = Depends(get_db)):
    """Server-to-server callback from face verification provider."""
    try:
        session = await FreelanceService.process_face_verification_webhook(
            db=db,
            session_token=payload.session_token,
            verification_id=payload.verification_id,
            status_val=payload.status,
            liveness_score=payload.liveness_score,
            reason=payload.reason
        )
        return ApiResponse(
            success=True,
            message="Webhook processed successfully",
            data={"verification_id": session.verification_id, "status": session.status}
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

