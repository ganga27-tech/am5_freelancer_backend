from sqlalchemy import Column, String, Integer, BigInteger, DateTime, Numeric, Text
from sqlalchemy.sql import func
from app.db.base_class import Base

class Freelancer(Base):
    __tablename__ = "freelancers"
    __mapper_args__ = {"exclude_properties": ["updated_at"]}

    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True, index=True)
    first_name = Column(String)
    last_name = Column(String, nullable=True)
    email = Column(String, unique=True, index=True)
    phone_number = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    referral_code = Column(String, unique=True, index=True)
    total_points = Column(Integer, default=0)
    status = Column(String, default="active")
    bank_name = Column(String, nullable=True)
    bank_account_number = Column(String, nullable=True)
    bank_account_name = Column(String, nullable=True)
    bank_ifsc_code = Column(String, nullable=True)

    # Extended profile attributes
    photo_url = Column(String, nullable=True)
    city = Column(String, nullable=True)
    state = Column(String, nullable=True)
    address = Column(Text, nullable=True)
    pincode = Column(String, nullable=True)
    bio = Column(Text, nullable=True)
    profile_status = Column(String, default="active")
    profile_completion_percentage = Column(Integer, default=25)
    bank_verification_status = Column(String, default="NOT_VERIFIED")
    kyc_status = Column(String, default="NOT_STARTED")  # NOT_STARTED, PENDING, VERIFIED, REJECTED
    face_verification_status = Column(String, default="NOT_STARTED")  # NOT_STARTED, PENDING, VERIFIED, FAILED

    # Wallet and rewards
    total_earnings = Column(Numeric(12, 2), default=0.00)
    available_balance = Column(Numeric(12, 2), default=0.00)
    pending_balance = Column(Numeric(12, 2), default=0.00)
    processing_balance = Column(Numeric(12, 2), default=0.00)
    total_withdrawn = Column(Numeric(12, 2), default=0.00)

    @property
    def full_name(self) -> str:
        parts = [self.first_name or "", self.last_name or ""]
        name = " ".join(p.strip() for p in parts if p.strip())
        return name or self.email or "Freelancer"
