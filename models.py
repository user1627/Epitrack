from sqlalchemy import Column, Integer, String, Boolean, DateTime
from datetime import datetime
from database import Base

class FieldReportModel(Base):
    __tablename__ = "field_reports"

    id = Column(Integer, primary_key=True, index=True)
    woreda = Column(String, nullable=False)
    disease_type = Column(String, nullable=False)
    case_count = Column(Integer, nullable=False)
    is_alert = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
