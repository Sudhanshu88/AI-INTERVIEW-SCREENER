from fastapi import FastAPI, HTTPException, Depends, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session, joinedload
from typing import List
from datetime import datetime
from contextlib import asynccontextmanager
import asyncio, csv, io, json, logging

# Local imports
from models import get_db, init_db
from models import Campaign, Candidate, Interview, Question, Response
from schemas import (
    CampaignResponse, CandidateResponse, InterviewResponse,
    ResponseCreate
)

# Import services safely
try:
    from services.ai_service import AIService
    from services.voice_service import VoiceService
    from services.call_service import CallService
except ImportError as e:
    raise ImportError(f"Required service missing: {e}")

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        logger.info("Initializing database...")
        init_db()
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise
    yield
    logger.info("Shutting down application...")

app = FastAPI(
    title="AI Interview Screener",
    description="Full-stack AI-powered interview screening system",
    version="1.0.0",
    lifespan=lifespan
)

# ✅ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change for production!
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ Initialize services
ai_service = AIService()
voice_service = VoiceService()
call_service = CallService()

@app.get("/")
async def root():
    return {"message": "AI Interview Screener API", "status": "active"}

@app.post("/campaigns", response_model=CampaignResponse)
async def create_campaign(
    title: str = Form(...),
    job_description: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Create a new campaign with AI-generated questions from job description."""
    try:
        jd_text = (await job_description.read()).decode("utf-8", errors="ignore")

        # ✅ Generate questions using AI
        questions_data = await ai_service.generate_questions(jd_text)
        if not questions_data:
            raise HTTPException(status_code=400, detail="AI could not generate questions")

        # ✅ Create campaign
        campaign = Campaign(
            title=title,
            job_description=jd_text,
            status="active",
            created_at=datetime.utcnow()
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

        # ✅ Save questions
        for idx, q_data in enumerate(questions_data):
            db.add(Question(
                campaign_id=campaign.id,
                question_text=q_data.get("question", ""),
                question_type=q_data.get("type", "general"),
                expected_criteria=json.dumps(q_data.get("criteria", {})),
                order_index=q_data.get("order", idx)
            ))
        db.commit()

        return CampaignResponse(
            id=campaign.id,
            title=campaign.title,
            job_description=campaign.job_description,
            status=campaign.status,
            created_at=campaign.created_at,
            questions_count=len(questions_data),
            candidates_count=0
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating campaign: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.post("/campaigns/{campaign_id}/candidates")
async def upload_candidates(
    campaign_id: int,
    candidates_file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload candidates CSV for a campaign."""
    campaign = db.query(Campaign).filter_by(id=campaign_id).first()
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    try:
        csv_content = (await candidates_file.read()).decode("utf-8", errors="ignore")
        csv_reader = csv.DictReader(io.StringIO(csv_content))

        candidates_created = 0
        for row in csv_reader:
            db.add(Candidate(
                campaign_id=campaign_id,
                name=row.get("name", "").strip(),
                email=row.get("email", "").strip(),
                phone=row.get("phone", "").strip(),
                status="pending"
            ))
            candidates_created += 1

        db.commit()
        return {"message": f"Successfully uploaded {candidates_created} candidates"}
    except Exception as e:
        logger.error(f"Error uploading candidates: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload candidates")

@app.get("/campaigns", response_model=List[CampaignResponse])
async def list_campaigns(db: Session = Depends(get_db)):
    """List all campaigns with summary statistics."""
    campaigns = db.query(Campaign).all()
    responses = []
    for c in campaigns:
        responses.append(CampaignResponse(
            id=c.id,
            title=c.title,
            job_description=c.job_description,
            status=c.status,
            created_at=c.created_at,
            questions_count=db.query(Question).filter_by(campaign_id=c.id).count(),
            candidates_count=db.query(Candidate).filter_by(campaign_id=c.id).count()
        ))
    return responses

@app.get("/campaigns/{campaign_id}/candidates", response_model=List[CandidateResponse])
async def get_campaign_candidates(campaign_id: int, db: Session = Depends(get_db)):
    """Get all candidates for a specific campaign."""
    candidates = db.query(Candidate).filter_by(campaign_id=campaign_id).all()
    result = []
    for c in candidates:
        interview = db.query(Interview).filter_by(candidate_id=c.id).first()
        result.append(CandidateResponse(
            id=c.id,
            name=c.name,
            email=c.email,
            phone=c.phone,
            status=c.status,
            interview_id=interview.id if interview else None,
            overall_score=interview.overall_score if interview else None,
            recommendation=interview.recommendation if interview else None
        ))
    return result

@app.post("/candidates/{candidate_id}/interview")
async def start_interview(candidate_id: int, db: Session = Depends(get_db)):
    """Start an interview for a candidate."""
    candidate = db.query(Candidate).filter_by(id=candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    campaign = db.query(Campaign).filter_by(id=candidate.campaign_id).first()
    questions = db.query(Question).filter_by(campaign_id=campaign.id).order_by(Question.order_index).all()

    try:
        interview = Interview(
            candidate_id=candidate_id,
            campaign_id=candidate.campaign_id,
            status="in_progress",
            started_at=datetime.utcnow()
        )
        db.add(interview)
        db.commit()
        db.refresh(interview)

        candidate.status = "interviewing"
        db.commit()

        call_result = await call_service.initiate_call(candidate.phone, candidate.name, questions, interview.id)
        return {
            "interview_id": interview.id,
            "call_id": call_result.get("call_id"),
            "status": "started",
            "message": f"Interview started for {candidate.name}"
        }
    except Exception as e:
        logger.error(f"Error starting interview: {e}")
        raise HTTPException(status_code=500, detail="Could not start interview")

@app.get("/interviews/{interview_id}", response_model=InterviewResponse)
async def get_interview(interview_id: int, db: Session = Depends(get_db)):
    """Get interview details with responses and scores."""
    interview = db.query(Interview).options(joinedload(Interview.responses).joinedload(Response.question)).filter_by(id=interview_id).first()
    if not interview:
        raise HTTPException(status_code=404, detail="Interview not found")

    return InterviewResponse(
        id=interview.id,
        candidate_id=interview.candidate_id,
        campaign_id=interview.campaign_id,
        status=interview.status,
        started_at=interview.started_at,
        completed_at=interview.completed_at,
        overall_score=interview.overall_score,
        communication_score=interview.communication_score,
        technical_score=interview.technical_score,
        recommendation=interview.recommendation,
        responses=[
            {
                "id": r.id,
                "question_text": r.question.question_text if r.question else None,
                "transcript": r.transcript,
                "score": r.score,
                "analysis": r.analysis,
                "audio_url": r.audio_url
            }
            for r in interview.responses
        ]
    )

# ... (Keep other endpoints similarly cleaned up)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
