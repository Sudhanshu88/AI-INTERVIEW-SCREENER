from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# ✅ Campaign Schemas
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

    class Config:
        orm_mode = True

# ✅ Candidate Schemas
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

    class Config:
        orm_mode = True

# ✅ Question Schemas
class QuestionResponse(BaseModel):
    id: int
    question_text: str
    question_type: str
    order_index: int

    class Config:
        orm_mode = True

# ✅ Response Schemas
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

    class Config:
        orm_mode = True

# ✅ Interview Schema
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

    class Config:
        orm_mode = True
