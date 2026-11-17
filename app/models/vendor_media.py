import datetime

from sqlalchemy import BigInteger, Column, DateTime, ForeignKey, String, Text

from app.db.base_class import Base


class VendorMedia(Base):
    """One row per file uploaded through POST /media/upload.

    Gives uploads a stable `media_id` so category APIs can reference
    (and validate ownership/type of) media instead of trusting raw URLs.
    """
    __tablename__ = "vendor_media"

    id = Column(BigInteger, primary_key=True, index=True)
    vendor_id = Column(BigInteger, ForeignKey("vendors.id"), index=True, nullable=False)
    media_type = Column(String(20), nullable=False)  # image | video
    url = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
