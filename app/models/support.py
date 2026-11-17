import datetime

from sqlalchemy import Column, String, BigInteger, DateTime, Text, ForeignKey

from app.db.base_class import Base


class SupportTicketMessage(Base):
    """A reply on a support ticket. The ticket's own description is its first message."""
    __tablename__ = "support_ticket_messages"

    id = Column(BigInteger, primary_key=True, index=True)
    ticket_id = Column(BigInteger, ForeignKey("support_tickets.id"), index=True, nullable=False)
    sender_type = Column(String(10), nullable=False)  # customer | staff
    sender_id = Column(BigInteger, nullable=True)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow, index=True)
