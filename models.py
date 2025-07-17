# models.py
from sqlalchemy import Column, Integer, String, Text, Float, DateTime, ForeignKey, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class Campaign(Base):
    __tablename__ = "campaigns"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    job_description = Column(Text, nullable=False)
    status = Column(String(50), default="active")  # active, paused, completed
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    questions = relationship("Question", back_populates="campaign")
    candidates = relationship("Candidate", back_populates="campaign")
    interviews = relationship("Interview", back_populates="campaign")

class Question(Base):
    __tablename__ = "questions"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    question_text = Column(Text, nullable=False)
    question_type = Column(String(50))  # behavioral, technical, situational
    expected_criteria = Column(Text)  # JSON string of evaluation criteria
    order_index = Column(Integer, default=0)
    
    # Relationships
    campaign = relationship("Campaign", back_populates="questions")
    responses = relationship("Response", back_populates="question")

class Candidate(Base):
    __tablename__ = "candidates"
    
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    name = Column(String(255), nullable=False)
    email = Column(String(255))
    phone = Column(String(20), nullable=False)
    status = Column(String(50), default="pending")  # pending, interviewing, interviewed, selected, rejected
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    campaign = relationship("Campaign", back_populates="candidates")
    interviews = relationship("Interview", back_populates="candidate")

class Interview(Base):
    __tablename__ = "interviews"
    
    id = Column(Integer, primary_key=True, index=True)
    candidate_id = Column(Integer, ForeignKey("candidates.id"), nullable=False)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"), nullable=False)
    status = Column(String(50), default="pending")  # pending, in_progress, completed, failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    
    # Scores
    overall_score = Column(Float)
    communication_score = Column(Float)
    technical_score = Column(Float)
    recommendation = Column(String(20))  # hire, no_hire, maybe
    
    # Call details
    call_id = Column(String(100))
    call_duration = Column(Integer)  # in seconds
    
    # Relationships
    candidate = relationship("Candidate", back_populates="interviews")
    campaign = relationship("Campaign", back_populates="interviews")
    responses = relationship("Response", back_populates="interview")

class Response(Base):
    __tablename__ = "responses"
    
    id = Column(Integer, primary_key=True, index=True)
    interview_id = Column(Integer, ForeignKey("interviews.id"), nullable=False)
    question_id = Column(Integer, ForeignKey("questions.id"), nullable=False)
    transcript = Column(Text)
    audio_url = Column(String(500))
    score = Column(Float)
    analysis = Column(Text)  # AI analysis of the response
    duration = Column(Integer)  # response duration in seconds
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    interview = relationship("Interview", back_populates="responses")
    question = relationship("Question", back_populates="responses")

# database.py
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
import os

# Database configuration
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:password@localhost/ai_interview_db")

# Handle SQLAlchemy 2.0 compatibility
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    """Initialize database tables."""
    from models import Base
    Base.metadata.create_all(bind=engine)

# schemas.py
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class CampaignCreate(BaseModel):
    title: str
    job_description: str

class CampaignResponse(BaseModel):
    id: int
    title: str
    job_description: str
    status: str
    created_at: datetime
    questions_count: int
    candidates_count: int

class CandidateCreate(BaseModel):
    name: str
    email: Optional[str] = None
    phone: str

class CandidateResponse(BaseModel):
    id: int
    name: str
    email: Optional[str]
    phone: str
    status: str
    interview_id: Optional[int] = None
    overall_score: Optional[float] = None
    recommendation: Optional[str] = None

class QuestionResponse(BaseModel):
    id: int
    question_text: str
    question_type: str
    order_index: int

class ResponseCreate(BaseModel):
    question_id: int
    transcript: str
    audio_url: Optional[str] = None
    duration: Optional[int] = None

class ResponseDetail(BaseModel):
    id: int
    question_text: str
    transcript: str
    score: Optional[float]
    analysis: Optional[str]
    audio_url: Optional[str]

class InterviewResponse(BaseModel):
    id: int
    candidate_id: int
    campaign_id: int
    status: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    overall_score: Optional[float]
    communication_score: Optional[float]
    technical_score: Optional[float]
    recommendation: Optional[str]
    responses: List[ResponseDetail]

class ScoreResponse(BaseModel):
    overall_score: float
    communication_score: float
    technical_score: float
    recommendation: str
    analysis: str