import uuid
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, desc, update, case

from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.freelancer import Freelancer
from app.models.catalog import ServiceCategory, ServiceSubcategory
from app.services.otp_service import otp_service
from app.services.upload_service import upload_service
from freelance_api.models import (
    FreelancerKycDocument,
    FreelancerKycSubmission,
    FreelancerFaceVerificationSession,
    FreelancerReferralLink,
    FreelancerReferralReward,
    FreelancerInstallationRule,
    FreelancerInstallationTracking,
    FreelancerRewardItem,
    FreelancerWalletTransaction,
    FreelancerPayoutRequest,
    FreelancerSetting,
    FreelancerNotification,
    FreelancerDeviceToken,
    FreelancerSupportTicket,
    FreelancerLegalPage,
    FreelancerLegalAcceptance,
    FreelancerBanner,
    FreelancerDemoVideo,
    FreelancerFaq,
)
from freelance_api.dependencies import mask_account_number

# In-memory challenge storage for password reset flows
_password_reset_challenges: Dict[str, Dict[str, Any]] = {}
_reset_tokens: Dict[str, Dict[str, Any]] = {}

class FreelanceService:
    @staticmethod
    async def login(db: AsyncSession, identifier: str, password: str) -> Tuple[Freelancer, str]:
        ident = identifier.strip().lower()
        stmt = select(Freelancer).where(
            or_(
                func.lower(Freelancer.email) == ident,
                Freelancer.phone_number == identifier.strip()
            )
        )
        res = await db.execute(stmt)
        freelancer = res.scalar_one_or_none()
        if not freelancer:
            raise ValueError("Invalid email/mobile or password")

        if not verify_password(password, freelancer.hashed_password):
            raise ValueError("Invalid email/mobile or password")

        if freelancer.status in ("inactive", "suspended", "blocked", "banned"):
            raise ValueError(f"Account is {freelancer.status}. Please contact support.")

        token = create_access_token(freelancer.id)
        return freelancer, token

    @staticmethod
    async def register(db: AsyncSession, full_name: str, mobile_number: str, email: str, password: str) -> Freelancer:
        clean_email = email.strip().lower()
        clean_mobile = mobile_number.replace("+", "").replace(" ", "").replace("-", "").strip()

        stmt = select(Freelancer).where(
            or_(
                func.lower(Freelancer.email) == clean_email,
                Freelancer.phone_number == clean_mobile
            )
        )
        res = await db.execute(stmt)
        if res.scalar_one_or_none():
            raise ValueError("An account with this email or mobile number already exists")

        name_parts = full_name.strip().split(" ", 1)
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        rand_suffix = secrets.token_hex(3).upper()
        ref_code = f"AM5{first_name[:3].upper()}{rand_suffix}"

        hashed_pw = get_password_hash(password)

        freelancer = Freelancer(
            first_name=first_name,
            last_name=last_name,
            email=clean_email,
            phone_number=clean_mobile,
            hashed_password=hashed_pw,
            referral_code=ref_code,
            total_points=50,
            status="active",
            profile_completion_percentage=25,
            kyc_status="NOT_STARTED",
            face_verification_status="NOT_STARTED",
            total_earnings=0.00,
            available_balance=0.00,
            pending_balance=0.00,
            processing_balance=0.00,
            total_withdrawn=0.00,
        )
        db.add(freelancer)
        await db.commit()
        await db.refresh(freelancer)

        setting = FreelancerSetting(
            freelancer_id=freelancer.id,
            privacy_preferences={
                "show_profile_in_directory": True,
                "allow_marketing_contact": True,
                "share_activity_status": True,
            },
            notification_preferences={
                "push_notifications": True,
                "email_notifications": True,
                "sms_notifications": True,
                "referral_alerts": True,
                "payout_alerts": True,
            },
            security_preferences={
                "two_factor_enabled": False,
                "login_alerts": True,
            }
        )
        db.add(setting)

        notif = FreelancerNotification(
            freelancer_id=freelancer.id,
            notification_id=f"ntf_{uuid.uuid4().hex[:8]}",
            title="Welcome to AM5 Freelancer!",
            body="Your account has been created. Complete your KYC to start earning rewards.",
            type="SYSTEM",
            deep_link="/profile/kyc"
        )
        db.add(notif)
        await db.commit()

        return freelancer

    @staticmethod
    async def request_password_reset(db: AsyncSession, identifier: str) -> Tuple[str, int]:
        ident = identifier.strip().lower()
        stmt = select(Freelancer).where(
            or_(
                func.lower(Freelancer.email) == ident,
                Freelancer.phone_number == identifier.strip()
            )
        )
        res = await db.execute(stmt)
        freelancer = res.scalar_one_or_none()
        if not freelancer:
            challenge_id = f"chl_{uuid.uuid4().hex[:12]}"
            return challenge_id, 300

        challenge_id = f"chl_{uuid.uuid4().hex[:12]}"
        otp = "12345" if freelancer.phone_number in otp_service.STATIC_TEST_NUMBERS else f"{secrets.randbelow(900000) + 100000}"
        
        await otp_service.store_otp(challenge_id, otp)
        _password_reset_challenges[challenge_id] = {
            "freelancer_id": freelancer.id,
            "otp": otp,
            "expires_at": datetime.utcnow() + timedelta(minutes=5)
        }
        return challenge_id, 300

    @staticmethod
    async def verify_otp(challenge_id: str, otp: str, purpose: str) -> str:
        challenge = _password_reset_challenges.get(challenge_id)
        if not challenge:
            raise ValueError("Verification challenge expired or invalid")

        if datetime.utcnow() > challenge["expires_at"]:
            _password_reset_challenges.pop(challenge_id, None)
            raise ValueError("OTP expired. Please request a new one.")

        if challenge["otp"] != otp.strip():
            raise ValueError("Incorrect OTP")

        reset_token = f"rst_{uuid.uuid4().hex}"
        _reset_tokens[reset_token] = {
            "freelancer_id": challenge["freelancer_id"],
            "expires_at": datetime.utcnow() + timedelta(minutes=15)
        }
        _password_reset_challenges.pop(challenge_id, None)
        return reset_token

    @staticmethod
    async def reset_password(db: AsyncSession, reset_token: str, new_password: str) -> None:
        token_data = _reset_tokens.get(reset_token)
        if not token_data or datetime.utcnow() > token_data["expires_at"]:
            _reset_tokens.pop(reset_token, None)
            raise ValueError("Reset token is invalid or expired")

        freelancer_id = token_data["freelancer_id"]
        stmt = select(Freelancer).where(Freelancer.id == freelancer_id)
        res = await db.execute(stmt)
        freelancer = res.scalar_one_or_none()
        if not freelancer:
            raise ValueError("Freelancer account not found")

        freelancer.hashed_password = get_password_hash(new_password)
        await db.commit()
        _reset_tokens.pop(reset_token, None)

    @staticmethod
    async def change_password(db: AsyncSession, freelancer: Freelancer, current_pw: str, new_pw: str) -> None:
        if not verify_password(current_pw, freelancer.hashed_password):
            raise ValueError("Current password does not match")
        freelancer.hashed_password = get_password_hash(new_pw)
        await db.commit()

    @staticmethod
    def calculate_completion(freelancer: Freelancer) -> Tuple[int, List[str], List[str]]:
        completed = []
        missing = []

        if freelancer.first_name and freelancer.email and freelancer.phone_number:
            completed.append("basic_info")
        else:
            missing.append("basic_info")

        if freelancer.city and freelancer.address and freelancer.pincode:
            completed.append("address_details")
        else:
            missing.append("address_details")

        if freelancer.bank_account_number and freelancer.bank_ifsc_code:
            completed.append("bank_details")
        else:
            missing.append("bank_details")

        if freelancer.kyc_status == "VERIFIED":
            completed.append("kyc_verification")
        else:
            missing.append("kyc_verification")

        total_pct = int((len(completed) / 4) * 100)
        return total_pct, completed, missing

    @staticmethod
    async def update_profile(db: AsyncSession, freelancer: Freelancer, update_data: Dict[str, Any]) -> Freelancer:
        for k, v in update_data.items():
            if v is not None and hasattr(freelancer, k):
                setattr(freelancer, k, v)

        pct, _, _ = FreelanceService.calculate_completion(freelancer)
        freelancer.profile_completion_percentage = pct
        await db.commit()
        await db.refresh(freelancer)
        return freelancer

    @staticmethod
    async def update_bank_details(db: AsyncSession, freelancer: Freelancer, data: Dict[str, Any]) -> Freelancer:
        ifsc = data["ifsc_code"].strip().upper()
        if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc):
            raise ValueError("Invalid IFSC code format (e.g. HDFC0001234)")

        freelancer.bank_account_name = data["account_holder_name"].strip()
        freelancer.bank_account_number = data["account_number"].strip()
        freelancer.bank_ifsc_code = ifsc
        freelancer.bank_name = data["bank_name"].strip()
        freelancer.bank_verification_status = "PENDING"

        pct, _, _ = FreelanceService.calculate_completion(freelancer)
        freelancer.profile_completion_percentage = pct
        await db.commit()
        await db.refresh(freelancer)
        return freelancer

    @staticmethod
    async def generate_referral_link(
        db: AsyncSession,
        freelancer: Freelancer,
        referral_type: str,
        validity_days: int = 15,
        target_sub_service_id: Optional[int] = None
    ) -> FreelancerReferralLink:
        validity = 7 if validity_days == 7 else 15
        expires_at = datetime.utcnow() + timedelta(days=validity)
        unique_token = secrets.token_hex(4).upper()
        code = f"{freelancer.referral_code}-{unique_token}"

        target_service_name = None
        target_url = f"https://am5royal.com/ref/{code}"

        if referral_type == "service" and target_sub_service_id:
            stmt = select(ServiceSubcategory).where(ServiceSubcategory.id == target_sub_service_id)
            res = await db.execute(stmt)
            sub = res.scalar_one_or_none()
            if sub:
                target_service_name = sub.name
                target_url = f"https://am5royal.com/services/{sub.id}?ref={code}"
        elif referral_type == "vendor":
            target_url = f"https://vendor.am5royal.com/register?ref={code}"
        else:
            referral_type = "customer"
            target_url = f"https://am5royal.com/signup?ref={code}"

        link = FreelancerReferralLink(
            freelancer_id=freelancer.id,
            referral_code=code,
            referral_type=referral_type,
            target_sub_service_id=target_sub_service_id,
            target_sub_service_name=target_service_name,
            url=target_url,
            validity_days=validity,
            status="active",
            expires_at=expires_at,
        )
        db.add(link)
        await db.commit()
        await db.refresh(link)
        return link

    @staticmethod
    async def validate_referral_code(db: AsyncSession, code: str) -> Dict[str, Any]:
        stmt = select(FreelancerReferralLink).where(FreelancerReferralLink.referral_code == code.strip())
        res = await db.execute(stmt)
        link = res.scalar_one_or_none()

        if not link:
            stmt_f = select(Freelancer).where(Freelancer.referral_code == code.strip())
            res_f = await db.execute(stmt_f)
            free = res_f.scalar_one_or_none()
            if free and free.status == "active":
                return {
                    "valid": True,
                    "status": "active",
                    "referral_type": "general",
                    "target_service": None,
                    "expires_at": None,
                    "referrer_name": free.full_name
                }
            return {"valid": False, "status": "not_found"}

        now = datetime.utcnow()
        if link.status != "active" or link.expires_at < now:
            return {
                "valid": False,
                "status": "expired" if link.expires_at < now else link.status,
                "referral_type": link.referral_type,
                "expires_at": link.expires_at.isoformat() + "Z",
            }

        link.clicks_count += 1
        await db.commit()

        target_service = None
        if link.target_sub_service_id:
            target_service = {
                "id": link.target_sub_service_id,
                "name": link.target_sub_service_name
            }

        stmt_f = select(Freelancer).where(Freelancer.id == link.freelancer_id)
        res_f = await db.execute(stmt_f)
        free = res_f.scalar_one_or_none()

        return {
            "valid": True,
            "status": "active",
            "referral_type": link.referral_type,
            "target_service": target_service,
            "expires_at": link.expires_at.isoformat() + "Z",
            "referrer_name": free.full_name if free else "AM5 Partner"
        }

    @staticmethod
    async def get_level_progress(freelancer: Freelancer) -> Dict[str, Any]:
        points = freelancer.total_points or 0

        if points < 250:
            level = "Bronze"
            next_level = "Silver"
            target = 250
            req = target - points
            pct = round((points / target) * 100, 1)
            benefits = ["Standard 5% commission on customer referrals", "Weekly payout cycle"]
        elif points < 1000:
            level = "Silver"
            next_level = "Gold"
            target = 1000
            req = target - points
            pct = round(((points - 250) / 750) * 100, 1)
            benefits = ["7.5% commission on referrals", "Priority customer lead routing", "48-hr fast payouts"]
        elif points < 3000:
            level = "Gold"
            next_level = "Platinum"
            target = 3000
            req = target - points
            pct = round(((points - 1000) / 2000) * 100, 1)
            benefits = ["10% commission on referrals", "Dedicated partner support", "24-hr express payouts", "Amazon vouchers"]
        else:
            level = "Platinum"
            next_level = None
            target = points
            req = 0
            pct = 100.0
            benefits = ["15% VIP commission rate", "Executive account manager", "Instant wallet withdrawals", "Exclusive milestone bonuses"]

        return {
            "current_level": level,
            "next_level": next_level,
            "current_points": points,
            "points_required_to_next_level": req,
            "progress_percentage": min(100.0, max(0.0, pct)),
            "benefits": benefits
        }

    @staticmethod
    async def get_installation_statistics(db: AsyncSession, freelancer: Freelancer) -> Dict[str, Any]:
        stmt = select(
            FreelancerInstallationTracking.app_type,
            func.count(FreelancerInstallationTracking.id).label("total_installs"),
            func.count(FreelancerInstallationTracking.activation_date).label("total_activations"),
            func.sum(
                case((FreelancerInstallationTracking.retention_status.in_(["eligible", "retained"]), 1), else_=0)
            ).label("total_eligible"),
        ).where(
            FreelancerInstallationTracking.freelancer_id == freelancer.id
        ).group_by(FreelancerInstallationTracking.app_type)

        res = await db.execute(stmt)
        rows = res.all()

        stats = {
            "customer_installs": 0,
            "customer_activations": 0,
            "customer_eligible": 0,
            "vendor_installs": 0,
            "vendor_activations": 0,
            "vendor_eligible": 0,
            "as_of_date": datetime.utcnow().isoformat() + "Z"
        }

        for row in rows:
            app_t = row.app_type.lower()
            if "customer" in app_t:
                stats["customer_installs"] = int(row.total_installs or 0)
                stats["customer_activations"] = int(row.total_activations or 0)
                stats["customer_eligible"] = int(row.total_eligible or 0)
            elif "vendor" in app_t:
                stats["vendor_installs"] = int(row.total_installs or 0)
                stats["vendor_activations"] = int(row.total_activations or 0)
                stats["vendor_eligible"] = int(row.total_eligible or 0)

        return stats

    @staticmethod
    async def get_milestone_eligibility(db: AsyncSession, freelancer: Freelancer, app_type: str = "customer") -> List[Dict[str, Any]]:
        stmt_rules = select(FreelancerInstallationRule).where(
            and_(
                FreelancerInstallationRule.app_type == app_type,
                FreelancerInstallationRule.is_active.is_(True)
            )
        ).order_by(FreelancerInstallationRule.milestone_target)
        rules_res = await db.execute(stmt_rules)
        rules = rules_res.scalars().all()

        stmt_count = select(func.count(FreelancerInstallationTracking.id)).where(
            and_(
                FreelancerInstallationTracking.freelancer_id == freelancer.id,
                FreelancerInstallationTracking.app_type == app_type,
                FreelancerInstallationTracking.retention_status.in_(["eligible", "retained"])
            )
        )
        count_res = await db.execute(stmt_count)
        current_count = count_res.scalar() or 0

        milestones = []
        for r in rules:
            target = r.milestone_target
            achieved = current_count >= target
            pct = min(100.0, round((current_count / target) * 100, 1)) if target > 0 else 100.0

            milestones.append({
                "milestone_id": r.id,
                "app_type": r.app_type,
                "target": target,
                "current_eligible_count": current_count,
                "progress_percentage": pct,
                "achieved": achieved,
                "is_eligible": achieved,
                "reward_amount": float(r.reward_amount),
                "voucher_title": r.voucher_title,
                "reward_status": "claimed" if achieved else ("eligible" if current_count >= target else "locked")
            })

        return milestones

    @staticmethod
    async def create_payout_request(db: AsyncSession, freelancer: Freelancer, amount: float) -> FreelancerPayoutRequest:
        if amount <= 0:
            raise ValueError("Payout amount must be greater than zero")

        if not freelancer.bank_account_number or not freelancer.bank_ifsc_code:
            raise ValueError("Bank details are required before requesting a payout")

        avail = float(freelancer.available_balance or 0.0)
        if amount > avail:
            raise ValueError(f"Insufficient available balance. Current available: ₹{avail:.2f}")

        min_payout = 500.0
        if amount < min_payout:
            raise ValueError(f"Minimum withdrawal amount is ₹{min_payout:.2f}")

        freelancer.available_balance = avail - amount
        freelancer.processing_balance = float(freelancer.processing_balance or 0.0) + amount

        payout_id = f"PO-{datetime.utcnow().strftime('%Y%m')}-{secrets.token_hex(3).upper()}"
        payout = FreelancerPayoutRequest(
            freelancer_id=freelancer.id,
            payout_id=payout_id,
            amount=amount,
            currency="INR",
            bank_name=freelancer.bank_name,
            bank_account_number=mask_account_number(freelancer.bank_account_number),
            bank_ifsc_code=freelancer.bank_ifsc_code,
            status="pending"
        )
        db.add(payout)

        txn_id = f"TXN-{uuid.uuid4().hex[:10].upper()}"
        txn = FreelancerWalletTransaction(
            freelancer_id=freelancer.id,
            transaction_id=txn_id,
            transaction_type="debit",
            category="withdrawal",
            description=f"Withdrawal request {payout_id} to bank {freelancer.bank_name}",
            amount=amount,
            balance_after=freelancer.available_balance,
            currency="INR",
            status="pending",
            reference_id=payout_id
        )
        db.add(txn)
        await db.commit()
        await db.refresh(payout)
        return payout

    @staticmethod
    async def submit_kyc_document(
        db: AsyncSession,
        freelancer: Freelancer,
        document_type: str,
        document_number: Optional[str],
        file_bytes: bytes,
        filename: str,
        content_type: str
    ) -> FreelancerKycDocument:
        url = await upload_service.upload_file(file_bytes, filename, content_type)
        if not url:
            url = f"https://cdn.am5royal.com/kyc/{uuid.uuid4().hex}-{filename}"

        doc = FreelancerKycDocument(
            freelancer_id=freelancer.id,
            document_type=document_type.lower().strip(),
            document_number=document_number,
            file_url=url,
            file_name=filename,
            file_size_bytes=len(file_bytes),
            mime_type=content_type,
            status="PENDING"
        )
        db.add(doc)
        await db.commit()
        await db.refresh(doc)
        return doc

    @staticmethod
    async def submit_kyc_application(
        db: AsyncSession,
        freelancer: Freelancer,
        aadhaar: Optional[str],
        pan: Optional[str],
        gst: Optional[str],
        document_ids: List[int]
    ) -> FreelancerKycSubmission:
        sub_id = f"KYC-{datetime.utcnow().strftime('%Y%m')}-{secrets.token_hex(3).upper()}"
        sub = FreelancerKycSubmission(
            freelancer_id=freelancer.id,
            submission_id=sub_id,
            aadhaar_number=aadhaar,
            pan_number=pan,
            gst_number=gst,
            document_ids=document_ids,
            status="PENDING"
        )
        db.add(sub)
        freelancer.kyc_status = "PENDING"
        pct, _, _ = FreelanceService.calculate_completion(freelancer)
        freelancer.profile_completion_percentage = pct

        await db.commit()
        await db.refresh(sub)
        return sub

    @staticmethod
    async def start_face_verification(db: AsyncSession, freelancer: Freelancer) -> FreelancerFaceVerificationSession:
        ver_id = f"fv_{secrets.token_hex(6)}"
        token = f"fvs_{secrets.token_urlsafe(24)}"
        expires_at = datetime.utcnow() + timedelta(minutes=20)

        session = FreelancerFaceVerificationSession(
            freelancer_id=freelancer.id,
            verification_id=ver_id,
            session_token=token,
            provider="hyperverge",
            status="PENDING",
            expires_at=expires_at
        )
        db.add(session)
        freelancer.face_verification_status = "PENDING"
        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    async def process_face_verification_webhook(
        db: AsyncSession,
        session_token: str,
        verification_id: str,
        status_val: str,
        liveness_score: Optional[float] = None,
        reason: Optional[str] = None
    ) -> FreelancerFaceVerificationSession:
        stmt = select(FreelancerFaceVerificationSession).where(
            and_(
                FreelancerFaceVerificationSession.session_token == session_token,
                FreelancerFaceVerificationSession.verification_id == verification_id
            )
        )
        res = await db.execute(stmt)
        session = res.scalar_one_or_none()
        if not session:
            raise ValueError("Verification session not found")

        status_norm = status_val.upper()
        if status_norm not in ("VERIFIED", "FAILED", "PENDING"):
            status_norm = "FAILED"

        session.status = status_norm
        session.liveness_score = liveness_score
        session.failure_reason = reason
        if status_norm == "VERIFIED":
            session.verified_at = datetime.utcnow()

        stmt_f = select(Freelancer).where(Freelancer.id == session.freelancer_id)
        res_f = await db.execute(stmt_f)
        freelancer = res_f.scalar_one_or_none()
        if freelancer:
            freelancer.face_verification_status = status_norm
            notif = FreelancerNotification(
                freelancer_id=freelancer.id,
                notification_id=f"ntf_{uuid.uuid4().hex[:8]}",
                title="Face Verification Update",
                body="Your face verification has been verified successfully." if status_norm == "VERIFIED" else f"Face verification was not successful: {reason or 'Please re-try.'}",
                type="FACE_VERIFICATION",
                reference_id=verification_id,
                deep_link="/profile/verification"
            )
            db.add(notif)

        await db.commit()
        await db.refresh(session)
        return session

    @staticmethod
    async def search_content(
        db: AsyncSession,
        query: str,
        scope: str = "all",
        page: int = 1,
        limit: int = 10
    ) -> Tuple[List[Dict[str, Any]], int]:
        q_term = f"%{query.strip().lower()}%"
        results: List[Dict[str, Any]] = []

        if scope in ("all", "services"):
            stmt_sub = select(ServiceSubcategory).where(
                and_(
                    ServiceSubcategory.is_active.is_(True),
                    or_(
                        func.lower(ServiceSubcategory.name).like(q_term),
                        func.lower(ServiceSubcategory.description).like(q_term)
                    )
                )
            ).limit(20)
            res_sub = await db.execute(stmt_sub)
            for sub in res_sub.scalars().all():
                results.append({
                    "id": f"service_{sub.id}",
                    "type": "service",
                    "title": sub.name,
                    "subtitle": sub.description or "AM5 Home Service",
                    "imageUrl": sub.icon_url,
                    "slug": sub.name.lower().replace(" ", "-"),
                    "targetUrl": f"/services/{sub.id}"
                })

        if scope in ("all", "faqs"):
            stmt_faq = select(FreelancerFaq).where(
                and_(
                    FreelancerFaq.is_active.is_(True),
                    or_(
                        func.lower(FreelancerFaq.question).like(q_term),
                        func.lower(FreelancerFaq.answer).like(q_term)
                    )
                )
            ).limit(10)
            res_faq = await db.execute(stmt_faq)
            for faq in res_faq.scalars().all():
                results.append({
                    "id": faq.faq_id,
                    "type": "faq",
                    "title": faq.question,
                    "subtitle": faq.answer[:120] + "..." if len(faq.answer) > 120 else faq.answer,
                    "imageUrl": None,
                    "slug": f"faq-{faq.id}",
                    "targetUrl": f"/support/faqs#{faq.faq_id}"
                })

        if scope in ("all", "videos"):
            stmt_vid = select(FreelancerDemoVideo).where(
                and_(
                    FreelancerDemoVideo.is_active.is_(True),
                    func.lower(FreelancerDemoVideo.title).like(q_term)
                )
            ).limit(10)
            res_vid = await db.execute(stmt_vid)
            for vid in res_vid.scalars().all():
                results.append({
                    "id": vid.video_id,
                    "type": "video",
                    "title": vid.title,
                    "subtitle": f"Demo video ({vid.duration})",
                    "imageUrl": vid.thumbnail_url,
                    "slug": vid.video_type,
                    "targetUrl": vid.video_url
                })

        total = len(results)
        offset = (page - 1) * limit
        paged_items = results[offset : offset + limit]
        return paged_items, total
