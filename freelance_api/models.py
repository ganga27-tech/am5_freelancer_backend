from datetime import datetime
from sqlalchemy import (
    Column,
    String,
    Integer,
    BigInteger,
    DateTime,
    Numeric,
    Text,
    Float,
    Boolean,
    ForeignKey,
    JSON,
)
from sqlalchemy.orm import relationship
from app.db.base_class import Base
from app.models.freelancer import Freelancer

def id_pk():
    return Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)

class FreelancerKycDocument(Base):
    __tablename__ = "freelancer_kyc_documents"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    document_type = Column(String, nullable=False)
    document_number = Column(String, nullable=True)
    file_url = Column(String, nullable=False)
    file_name = Column(String, nullable=True)
    file_size_bytes = Column(Integer, nullable=True)
    mime_type = Column(String, nullable=True)
    status = Column(String, default="PENDING")
    rejection_reason = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerKycSubmission(Base):
    __tablename__ = "freelancer_kyc_submissions"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    submission_id = Column(String, unique=True, index=True)
    aadhaar_number = Column(String, nullable=True)
    pan_number = Column(String, nullable=True)
    gst_number = Column(String, nullable=True)
    document_ids = Column(JSON, default=list)
    status = Column(String, default="PENDING")
    rejection_reason = Column(Text, nullable=True)
    submitted_at = Column(DateTime, default=datetime.utcnow)
    reviewed_at = Column(DateTime, nullable=True)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerFaceVerificationSession(Base):
    __tablename__ = "freelancer_face_verifications"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    verification_id = Column(String, unique=True, index=True)
    session_token = Column(String, unique=True, index=True)
    provider = Column(String, default="hyperverge")
    status = Column(String, default="NOT_STARTED")
    selfie_url = Column(String, nullable=True)
    liveness_score = Column(Float, nullable=True)
    failure_reason = Column(Text, nullable=True)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    verified_at = Column(DateTime, nullable=True)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerReferralLink(Base):
    __tablename__ = "freelancer_referral_links"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    referral_code = Column(String, unique=True, index=True)
    referral_type = Column(String, nullable=False)
    target_sub_service_id = Column(BigInteger, nullable=True)
    target_sub_service_name = Column(String, nullable=True)
    url = Column(String, nullable=False)
    validity_days = Column(Integer, default=15)
    status = Column(String, default="active")
    clicks_count = Column(Integer, default=0)
    conversions_count = Column(Integer, default=0)
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerReferralReward(Base):
    __tablename__ = "freelancer_referral_rewards"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    event_type = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    points = Column(Integer, default=0)
    amount = Column(Numeric(10, 2), default=0.00)
    currency = Column(String, default="INR")
    status = Column(String, default="approved")
    reference_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerInstallationRule(Base):
    __tablename__ = "freelancer_installation_rules"

    id = id_pk()
    app_type = Column(String, nullable=False, index=True)
    milestone_target = Column(Integer, nullable=False)
    reward_amount = Column(Numeric(10, 2), default=0.00)
    currency = Column(String, default="INR")
    voucher_type = Column(String, nullable=True)
    voucher_title = Column(String, nullable=True)
    voucher_value = Column(Numeric(10, 2), default=0.00)
    conditions = Column(Text, nullable=True)
    retention_days = Column(Integer, default=30)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FreelancerInstallationTracking(Base):
    __tablename__ = "freelancer_installation_trackings"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    tracking_id = Column(String, unique=True, index=True)
    referral_code = Column(String, index=True)
    app_type = Column(String, nullable=False)
    device_id = Column(String, nullable=True)
    install_date = Column(DateTime, default=datetime.utcnow)
    activation_date = Column(DateTime, nullable=True)
    retention_days_completed = Column(Integer, default=0)
    retention_status = Column(String, default="pending")
    eligibility_status = Column(String, default="in_review")
    reward_status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerRewardItem(Base):
    __tablename__ = "freelancer_reward_items"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    reward_id = Column(String, unique=True, index=True)
    reward_type = Column(String, default="referral")
    title = Column(String, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="INR")
    status = Column(String, default="pending")
    reference_id = Column(String, nullable=True)
    paid_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerWalletTransaction(Base):
    __tablename__ = "freelancer_wallet_transactions"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    transaction_id = Column(String, unique=True, index=True)
    transaction_type = Column(String, nullable=False)
    category = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    amount = Column(Numeric(10, 2), nullable=False)
    balance_after = Column(Numeric(10, 2), default=0.00)
    currency = Column(String, default="INR")
    status = Column(String, default="completed")
    reference_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerPayoutRequest(Base):
    __tablename__ = "freelancer_payout_requests"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    payout_id = Column(String, unique=True, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String, default="INR")
    bank_name = Column(String, nullable=True)
    bank_account_number = Column(String, nullable=True)
    bank_ifsc_code = Column(String, nullable=True)
    status = Column(String, default="pending")
    rejection_reason = Column(Text, nullable=True)
    payout_ref = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerSetting(Base):
    __tablename__ = "freelancer_settings"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), unique=True, index=True)
    privacy_preferences = Column(JSON, default=dict)
    notification_preferences = Column(JSON, default=dict)
    security_preferences = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerNotification(Base):
    __tablename__ = "freelancer_notifications"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    notification_id = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    body = Column(Text, nullable=False)
    type = Column(String, default="SYSTEM")
    reference_id = Column(String, nullable=True)
    deep_link = Column(String, nullable=True)
    is_read = Column(Boolean, default=False)
    read_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerDeviceToken(Base):
    __tablename__ = "freelancer_device_tokens"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    device_id = Column(String, nullable=False, index=True)
    platform = Column(String, nullable=False)
    device_token = Column(String, nullable=False)
    app_version = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    freelancer = relationship("Freelancer", foreign_keys=[freelancer_id])

class FreelancerSupportTicket(Base):
    __tablename__ = "freelancer_support_tickets"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="SET NULL"), nullable=True, index=True)
    ticket_number = Column(String, unique=True, index=True)
    ticket_type = Column(String, default="support_ticket")
    full_name = Column(String, nullable=False)
    email = Column(String, nullable=False)
    category = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    page_url = Column(String, nullable=True)
    device_details = Column(JSON, nullable=True)
    attachments = Column(JSON, default=list)
    status = Column(String, default="open")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class FreelancerLegalPage(Base):
    __tablename__ = "freelancer_legal_pages"

    id = id_pk()
    slug = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    version = Column(String, default="1.0")
    effective_date = Column(DateTime, default=datetime.utcnow)
    last_updated_date = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_active = Column(Boolean, default=True)

class FreelancerLegalAcceptance(Base):
    __tablename__ = "freelancer_legal_acceptances"

    id = id_pk()
    freelancer_id = Column(BigInteger, ForeignKey("freelancers.id", ondelete="CASCADE"), index=True)
    document_slug = Column(String, nullable=False)
    document_version = Column(String, nullable=False)
    ip_address = Column(String, nullable=True)
    accepted_at = Column(DateTime, default=datetime.utcnow)

class FreelancerBanner(Base):
    __tablename__ = "freelancer_banners"

    id = id_pk()
    banner_id = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    subtitle = Column(String, nullable=True)
    image_url = Column(String, nullable=False)
    mobile_image_url = Column(String, nullable=True)
    placement = Column(String, nullable=False, index=True)
    target_audience = Column(String, default="freelancer")
    category_id = Column(BigInteger, nullable=True)
    action_type = Column(String, default="navigate")
    action_value = Column(String, nullable=True)
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class FreelancerDemoVideo(Base):
    __tablename__ = "freelancer_demo_videos"

    id = id_pk()
    video_id = Column(String, unique=True, index=True)
    title = Column(String, nullable=False)
    video_type = Column(String, nullable=False)
    audience = Column(String, default="freelancer")
    video_url = Column(String, nullable=False)
    thumbnail_url = Column(String, nullable=False)
    duration = Column(String, default="03:00")
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class FreelancerFaq(Base):
    __tablename__ = "freelancer_faqs"

    id = id_pk()
    faq_id = Column(String, unique=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    audience = Column(String, default="freelancer")
    display_order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
