import datetime

from sqlalchemy import Column, String, Integer, DateTime

from app.db.base_class import Base


class SearchQueryStat(Base):
    """How often each search term was used (only terms that returned results). Feeds /search/popular."""
    __tablename__ = "search_query_stats"

    term = Column(String(60), primary_key=True)  # lower-case, trimmed
    hit_count = Column(Integer, nullable=False, default=0)
    last_searched_at = Column(DateTime, nullable=False, default=datetime.datetime.utcnow, index=True)
