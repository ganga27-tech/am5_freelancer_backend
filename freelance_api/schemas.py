from datetime import datetime
from typing import Generic, TypeVar, Optional, List, Dict, Any
from pydantic import BaseModel, EmailStr, Field, field_validator

T = TypeVar("T")

class ApiResponse(BaseModel, Generic[T]):
    success: bool = True
    message: str = "Success"
    data: Optional[T] = None

class PaginatedData(BaseModel, Generic[T]):
    items: List[T] = []
    page: int = 1
    limit: int = 10
    total: int = 0
    hasMore: bool = False
    unreadCount: Optional[int] = None

# --- Auth ---

class LoginRequest(BaseModel):
    identifier: str
    password: str

class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=2)
    mobile_number: str = Field(..., min_length=10, max_length=15)
    email: EmailStr
    password: str = Field(..., min_length=6)
    confirm_password: str = Field(..., min_length=6)

    @field_validator("confirm_password")
    @classmethod
    def match_passwords(cls, v: str, info):
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match")
        return v

class ForgotPasswordRequest(BaseModel):
    identifier: str
    preferred_channel: Optional[str] = "sms"

class VerifyOtpRequest(BaseModel):
    challenge_id: str
    otp: str
    purpose: str = "password_recovery"

class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str = Field(..., min_length=6)
    confirm_new_password: str = Field(..., min_length=6)

    @field_validator("confirm_new_password")
    @classmethod
    def match_reset_passwords(cls, v: str, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)
    confirm_new_password: str = Field(..., min_length=6)

    @field_validator("confirm_new_password")
    @classmethod
    def match_new_passwords(cls, v: str, info):
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match")
        return v

class UserSummary(BaseModel):
    user_id: int
    full_name: str
    mobile: Optional[str] = None
    email: Optional[str] = None
    profile_status: str = "active"

class AuthTokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    expires_in: int = 2592000
    user: UserSummary

class RegistrationResponse(BaseModel):
    user_id: int
    registration_status: str = "completed"
    verification_required: bool = False
    next_step: str = "login"

class ChallengeResponse(BaseModel):
    challenge_id: str
    expiry_seconds: int = 300
    message: str

class OtpVerificationResponse(BaseModel):
    verified: bool
    reset_token: Optional[str] = None
    message: str

# --- Banners & Videos ---

class BannerItemResponse(BaseModel):
    id: str
    title: str
    subtitle: Optional[str] = None
    image_url: str
    mobile_image_url: Optional[str] = None
    placement: str
    target_audience: str
    action_type: Optional[str] = None
    action_value: Optional[str] = None
    priority: int = 0
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    active: bool = True

class DemoVideoItemResponse(BaseModel):
    video_id: str
    title: str
    type: str
    video_url: str
    thumbnail_url: str
    duration: str
    display_order: int
    active_status: bool

class FaqItemResponse(BaseModel):
    faq_id: str
    question: str
    answer: str
    category: str
    display_order: int

# --- Services ---

class ServiceCategoryItemResponse(BaseModel):
    id: int
    name: str
    slug: str
    category_image_url: Optional[str] = None
    banner_url: Optional[str] = None
    active_status: bool = True
    display_order: int = 0

class ServiceSubcategoryItemResponse(BaseModel):
    id: int
    name: str
    slug: str
    image_url: Optional[str] = None
    banner_url: Optional[str] = None
    active_status: bool = True
    referral_eligibility: bool = True

# --- Referrals ---

class GenerateReferralLinkRequest(BaseModel):
    referral_type: str  # customer, vendor, service
    target_sub_service_id: Optional[int] = None
    validity_days: int = 15

    @field_validator("validity_days")
    @classmethod
    def check_validity(cls, v: int):
        return 7 if v == 7 else 15

class ReferralLinkItemResponse(BaseModel):
    referral_id: str
    referral_code: str
    referral_type: str
    target_service_id: Optional[int] = None
    target_service_name: Optional[str] = None
    url: str
    created_at: str
    expires_at: str
    status: str
    clicks_count: int = 0
    conversions_count: int = 0

class ReferralValidationResponse(BaseModel):
    valid: bool
    status: str
    referral_type: Optional[str] = None
    target_service: Optional[Dict[str, Any]] = None
    expires_at: Optional[str] = None
    referrer_name: Optional[str] = None

class ReferralRewardsSummaryResponse(BaseModel):
    total_points: int = 0
    available_points: int = 0
    pending_points: int = 0
    redeemed_points: int = 0
    currency_equivalent: float = 0.0

class ReferralLevelProgressResponse(BaseModel):
    current_level: str
    next_level: Optional[str] = None
    current_points: int = 0
    points_required_to_next_level: int = 0
    progress_percentage: float = 0.0
    benefits: List[str] = []

class ReferralPointHistoryItem(BaseModel):
    transaction_id: str
    event_description: str
    points: int
    amount: Optional[float] = None
    status: str
    created_at: str
    reference_id: Optional[str] = None

class ReferralRuleItem(BaseModel):
    tier: str
    criteria: str
    points_per_referral: int
    cash_value: float
    description: str

class ReferralRulesResponse(BaseModel):
    rules: List[ReferralRuleItem]
    guidelines: List[str]
    retention_period_days: int = 30

# --- App Installation & Milestones ---

class MilestoneRewardRule(BaseModel):
    milestone_id: int
    app_type: str
    target_count: int
    reward_amount: float
    currency: str = "INR"
    voucher_type: Optional[str] = None
    voucher_title: Optional[str] = None
    voucher_value: float = 0.0
    conditions: str = ""
    retention_days: int = 30

class InstallationRulesResponse(BaseModel):
    app_type: str
    milestones: List[MilestoneRewardRule]
    retention_days: int = 30
    last_updated_date: str

class InstallationStatisticsResponse(BaseModel):
    customer_installs: int = 0
    customer_activations: int = 0
    customer_eligible: int = 0
    vendor_installs: int = 0
    vendor_activations: int = 0
    vendor_eligible: int = 0
    as_of_date: str

class InstallationTrackingItem(BaseModel):
    tracking_id: str
    app_type: str
    referral_code: str
    install_date: Optional[str] = None
    activation_date: Optional[str] = None
    retention_days_completed: int = 0
    retention_status: str
    eligibility_status: str
    reward_status: str

class MilestoneEligibilityProgress(BaseModel):
    milestone_id: int
    app_type: str
    target: int
    current_eligible_count: int
    progress_percentage: float
    achieved: bool
    is_eligible: bool
    reward_amount: float
    voucher_title: Optional[str] = None
    reward_status: str

class InstallationEligibilityResponse(BaseModel):
    app_type: str
    milestones: List[MilestoneEligibilityProgress]

class InstallationRewardStatusItem(BaseModel):
    reward_id: str
    app_type: str
    milestone: int
    reward_amount: float
    voucher_title: Optional[str] = None
    status: str
    eligibility_reason: Optional[str] = None
    updated_date: str

# --- Rewards ---

class RewardsSummaryResponse(BaseModel):
    total_rewards: float = 0.0
    approved_rewards: float = 0.0
    pending_rewards: float = 0.0
    processing_rewards: float = 0.0
    paid_rewards: float = 0.0
    cashback_rewards: float = 0.0
    currency: str = "INR"

class RewardHistoryItem(BaseModel):
    reward_id: str
    reward_type: str
    title: str
    amount: float
    currency: str = "INR"
    status: str
    reference_id: Optional[str] = None
    created_at: str
    updated_at: str
    paid_date: Optional[str] = None

# --- Wallet ---

class WalletSummaryResponse(BaseModel):
    total_earnings: float = 0.0
    available_balance: float = 0.0
    pending_balance: float = 0.0
    processing_balance: float = 0.0
    total_withdrawn: float = 0.0
    currency: str = "INR"
    last_transaction_date: Optional[str] = None

class WalletTransactionItem(BaseModel):
    transaction_id: str
    type: str
    category: str
    description: str
    amount: float
    balance_after: Optional[float] = None
    currency: str = "INR"
    status: str
    date: str
    reference_id: Optional[str] = None

class PayoutRequestInput(BaseModel):
    amount: float = Field(..., gt=0)

class PayoutRequestResponse(BaseModel):
    payout_id: str
    amount: float
    currency: str = "INR"
    bank_name: str
    masked_account_number: str
    status: str
    created_at: str

# --- Profile & Bank ---

class FreelancerProfileResponse(BaseModel):
    user_id: int
    full_name: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    photo_url: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    bio: Optional[str] = None
    profile_status: str = "active"
    completion_percentage: int = 25
    kyc_status: str = "NOT_STARTED"
    referral_code: Optional[str] = None

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    bio: Optional[str] = None

class BankDetailsResponse(BaseModel):
    account_holder: Optional[str] = None
    masked_account_number: Optional[str] = None
    ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    verification_status: str = "NOT_VERIFIED"

class UpdateBankDetailsRequest(BaseModel):
    account_holder_name: str = Field(..., min_length=2)
    account_number: str = Field(..., min_length=8, max_length=20)
    ifsc_code: str = Field(..., min_length=11, max_length=11)
    bank_name: str = Field(..., min_length=2)

class ProfileCompletionResponse(BaseModel):
    completion_percentage: int
    profile_status: str
    completed_fields: List[str]
    missing_fields: List[str]

class PhotoUploadResponse(BaseModel):
    photo_url: str
    upload_status: str = "success"

# --- KYC & Face Verification ---

class KycDocumentResponse(BaseModel):
    file_id: int
    document_type: str
    file_url: str
    upload_status: str = "success"
    review_status: str = "PENDING"

class KycSubmissionRequest(BaseModel):
    aadhaar_number: Optional[str] = None
    pan_number: Optional[str] = None
    gst_number: Optional[str] = None
    document_ids: List[int] = Field(default_factory=list)

class KycSubmissionResponse(BaseModel):
    submission_id: str
    submitted_date: str
    kyc_status: str = "PENDING"
    next_steps: str = "Under review by AM5 verification team"

class KycStatusResponse(BaseModel):
    overall_status: str
    document_statuses: List[Dict[str, Any]] = []
    submission_date: Optional[str] = None
    rejection_reason: Optional[str] = None

class FaceVerificationStartRequest(BaseModel):
    consent: bool = True

class FaceVerificationStartResponse(BaseModel):
    verification_id: str
    session_token: str
    status: str = "NOT_STARTED"
    provider: str = "hyperverge"
    sdk_config: Dict[str, Any]

class FaceVerificationStatusResponse(BaseModel):
    verification_id: str
    status: str
    verified_at: Optional[str] = None
    failure_reason: Optional[str] = None

class FaceVerificationWebhookPayload(BaseModel):
    session_token: str
    verification_id: str
    status: str
    liveness_score: Optional[float] = None
    provider_signature: Optional[str] = None
    reason: Optional[str] = None

# --- Settings ---

class PrivacyPreferences(BaseModel):
    show_profile_in_directory: bool = True
    allow_marketing_contact: bool = True
    share_activity_status: bool = True

class NotificationPreferences(BaseModel):
    push_notifications: bool = True
    email_notifications: bool = True
    sms_notifications: bool = True
    referral_alerts: bool = True
    payout_alerts: bool = True

class SecurityPreferences(BaseModel):
    two_factor_enabled: bool = False
    login_alerts: bool = True

class FreelancerSettingsResponse(BaseModel):
    privacy: PrivacyPreferences
    notifications: NotificationPreferences
    security: SecurityPreferences

class UpdatePrivacyPreferencesRequest(BaseModel):
    show_profile_in_directory: Optional[bool] = None
    allow_marketing_contact: Optional[bool] = None
    share_activity_status: Optional[bool] = None

class UpdateNotificationPreferencesRequest(BaseModel):
    push_notifications: Optional[bool] = None
    email_notifications: Optional[bool] = None
    sms_notifications: Optional[bool] = None
    referral_alerts: Optional[bool] = None
    payout_alerts: Optional[bool] = None

class UpdateSecurityPreferencesRequest(BaseModel):
    two_factor_enabled: Optional[bool] = None
    login_alerts: Optional[bool] = None

# --- Support & Legal ---

class ContactSupportRequest(BaseModel):
    full_name: str = Field(..., min_length=2)
    email_address: EmailStr
    query_category: str
    subject: str = Field(..., min_length=4)
    query_description: str = Field(..., min_length=10)

class SupportTicketResponse(BaseModel):
    ticket_id: int
    ticket_number: str
    status: str = "open"
    created_date: str
    acknowledgement_message: str

class ReportProblemRequest(BaseModel):
    problem_category: str
    problem_description: str = Field(..., min_length=10)
    page_url: Optional[str] = None
    browser_details: Optional[Dict[str, Any]] = None
    attachments: Optional[List[str]] = Field(default_factory=list)

class ReportProblemResponse(BaseModel):
    report_id: str
    status: str = "open"
    created_date: str

class LegalPageResponse(BaseModel):
    slug: str
    title: str
    content: str
    version: str
    effective_date: str
    last_updated_date: str

class RecordLegalAcceptanceRequest(BaseModel):
    document_slug: str
    document_version: str

class LegalAcceptanceResponse(BaseModel):
    acceptance_status: str = "recorded"
    timestamp: str

# --- Notifications & Devices ---

class NotificationItemResponse(BaseModel):
    notificationId: str
    title: str
    body: str
    type: str
    referenceId: Optional[str] = None
    deepLink: Optional[str] = None
    isRead: bool
    createdAt: str

class DeviceRegisterRequest(BaseModel):
    platform: str
    deviceToken: str
    appVersion: Optional[str] = None

class DeviceRegisterResponse(BaseModel):
    status: str = "registered"
    device_id: str

# --- Search ---

class SearchResultItem(BaseModel):
    id: str
    type: str
    title: str
    subtitle: Optional[str] = None
    imageUrl: Optional[str] = None
    slug: Optional[str] = None
    targetUrl: str

class SearchResponse(BaseModel):
    query: str
    items: List[SearchResultItem]
    page: int
    limit: int
    total: int
    hasMore: bool
