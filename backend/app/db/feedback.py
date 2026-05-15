import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum as SAEnum, String, Text, Uuid

from backend.app.db.models import Base


class FeedbackType(str, enum.Enum):
    bug = "bug"
    feature = "feature"
    general = "general"


class Feedback(Base):
    __tablename__ = "feedback"

    id = Column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(SAEnum(FeedbackType, name="feedback_type", create_type=False), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    email = Column(String(254), nullable=True)
    page_context = Column(String(200), nullable=True)
    user_agent = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
