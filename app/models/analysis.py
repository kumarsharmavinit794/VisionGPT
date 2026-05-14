import uuid
from sqlalchemy import Column, String, Text, DateTime, ForeignKey, Float, Integer, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.db.base import Base


class ImageAnalysis(Base):
    __tablename__ = "image_analysis"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    file_id = Column(UUID(as_uuid=True), ForeignKey("uploaded_files.id"), nullable=False, index=True)
    summary = Column(Text)
    ocr_text = Column(Text)
    detected_objects = Column(JSON)
    ui_elements = Column(JSON)
    tables = Column(JSON)
    forms = Column(JSON)
    colors = Column(JSON)
    chart_analysis = Column(Text)
    document_type = Column(String(100))
    confidence_score = Column(Float)
    ai_response = Column(Text)
    json_response = Column(JSON)
    token_count = Column(Integer)
    tags = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relationships
    file = relationship("UploadedFile", back_populates="analyses")
