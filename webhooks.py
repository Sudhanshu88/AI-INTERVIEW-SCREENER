# webhooks.py - Add these endpoints to main.py
from fastapi import Request, HTTPException, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session
import json
from services.voice_service import VoiceService
from services.call_service import CallService
from models import Interview, Question, Response as ResponseModel, Candidate
from database import get_db

# Initialize services
voice_service = VoiceService()
call_service = CallService()

@app.post("/webhooks/call/start/{interview_id}")
async def handle_call_start(interview_id: int, request: Request, db: Session = Depends(get_db)):
    """Handle initial call connection."""
    try:
        # Get interview and candidate details
        interview = db.query(Interview).filter(Interview.id == interview_id).first()
        if not interview:
            raise HTTPException(status_code=404, detail="Interview not found")
        
        candidate = db.query(Candidate).filter(Candidate.id == interview.candidate_id).first()
        
        # Generate welcome TwiML
        twiml = call_service.generate_welcome_twiml(candidate.name, interview_id)
        
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        print(f"Error in call start: {e}")
        # Return error TwiML
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="Polly.Joanna">Sorry, there was an error starting the interview. Please try again later.</Say>
            <Hangup/>
        </Response>"""
        return Response(content=error_twiml, media_type="application/xml")

@app.post("/webhooks/call/question/{interview_id}")
async def handle_question_delivery(interview_id: int, request: Request, db: Session = Depends(get_db)):
    """Handle question delivery during interview."""
    try:
        # Get interview context
        context = call_service._get_interview_context(interview_id)
        if not context:
            raise HTTPException(status_code=404, detail="Interview context not found")
        
        current_index = context['current_question_index']
        questions = context['questions']
        
        # Check if we've reached the end
        if current_index >= len(questions):
            twiml = call_service.generate_completion_twiml()
            return Response(content=twiml, media_type="application/xml")
        
        # Get current question
        current_question = questions[current_index]
        
        # Generate question TwiML
        twiml = call_service.generate_question_twiml(
            current_question['text'], 
            interview_id, 
            current_index
        )
        
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        print(f"Error in question delivery: {e}")
        # Return error TwiML
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="Polly.Joanna">Sorry, there was an error with the question. Moving to the next one.</Say>
            <Redirect>/webhooks/call/next/{}</Redirect>
        </Response>""".format(interview_id)
        return Response(content=error_twiml, media_type="application/xml")

@app.post("/webhooks/call/response/{interview_id}/{question_index}")
async def handle_response_capture(
    interview_id: int, 
    question_index: int, 
    request: Request, 
    db: Session = Depends(get_db)
):
    """Handle candidate response capture."""
    try:
        form_data = await request.form()
        
        # Get speech result from Twilio
        speech_result = form_data.get('SpeechResult', '')
        confidence = float(form_data.get('Confidence', 0.0))
        recording_url = form_data.get('RecordingUrl', '')
        
        # Get interview context
        context = call_service._get_interview_context(interview_id)
        if not context:
            raise HTTPException(status_code=404, detail="Interview context not found")
        
        # Get current question
        current_question = context['questions'][question_index]
        
        # Save response to database
        response_record = ResponseModel(
            interview_id=interview_id,
            question_id=current_question['id'],
            transcript=speech_result,
            audio_url=recording_url,
            score=None,  # Will be filled by AI analysis
            analysis=None,  # Will be filled by AI analysis
            duration=None  # Could be calculated from recording
        )
        
        db.add(response_record)
        db.commit()
        db.refresh(response_record)
        
        # Trigger AI analysis asynchronously
        asyncio.create_task(analyze_response_async(response_record.id, db))
        
        # Move to next question
        context['current_question_index'] += 1
        call_service._update_interview_context(interview_id, context)
        
        # Generate next question or completion TwiML
        if context['current_question_index'] >= len(context['questions']):
            # Interview complete
            twiml = call_service.generate_completion_twiml()
            
            # Mark interview as completed
            interview = db.query(Interview).filter(Interview.id == interview_id).first()
            interview.status = "completed"
            interview.completed_at = datetime.utcnow()
            db.commit()
            
            # Trigger final analysis
            asyncio.create_task(complete_interview_analysis(interview_id, db))
        else:
            # Continue to next question
            next_question = context['questions'][context['current_question_index']]
            twiml = call_service.generate_question_twiml(
                next_question['text'], 
                interview_id, 
                context['current_question_index']
            )
        
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        print(f"Error in response capture: {e}")
        # Continue to next question on error
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="Polly.Joanna">Thank you for your response. Let's continue with the next question.</Say>
            <Redirect>/webhooks/call/next/{}</Redirect>
        </Response>""".format(interview_id)
        return Response(content=error_twiml, media_type="application/xml")

@app.post("/webhooks/call/next/{interview_id}")
async def handle_next_question(interview_id: int, request: Request):
    """Handle moving to next question."""
    try:
        # Get interview context
        context = call_service._get_interview_context(interview_id)
        if not context:
            raise HTTPException(status_code=404, detail="Interview context not found")
        
        # Move to next question
        context['current_question_index'] += 1
        call_service._update_interview_context(interview_id, context)
        
        # Redirect to question handler
        twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Redirect>/webhooks/call/question/{interview_id}</Redirect>
        </Response>"""
        
        return Response(content=twiml, media_type="application/xml")
        
    except Exception as e:
        print(f"Error in next question: {e}")
        # End interview on error
        error_twiml = """<?xml version="1.0" encoding="UTF-8"?>
        <Response>
            <Say voice="Polly.Joanna">Thank you for your time. The interview is now complete.</Say>
            <Hangup/>
        </Response>"""
        return Response(content=error_twiml, media_type="application/xml")

@app.post("/webhooks/call/status")
async def handle_call_status(request: Request, db: Session = Depends(get_db)):
    """Handle call status updates from Twilio."""
    try:
        form_data = await request.form()
        
        call_sid = form_data.get('CallSid')
        call_status = form_data.get('CallStatus')
        call_duration = form_data.get('CallDuration')
        
        # Update interview record with call details
        # This would require storing call_sid in the interview record
        print(f"Call {call_sid} status: {call_status}, duration: {call_duration}")
        
        return {"status": "ok"}
        
    except Exception as e:
        print(f"Error in call status: {e}")
        return {"status": "error"}

async def analyze_response_async(response_id: int, db: Session):
    """Asynchronously analyze a candidate response."""
    try:
        from services.ai_service import AIService
        ai_service = AIService()
        
        # Get response and question
        response = db.query(ResponseModel).filter(ResponseModel.id == response_id).first()
        question = db.query(Question).filter(Question.id == response.question_id).first()
        
        if response and question:
            # Analyze with AI
            analysis = await ai_service.analyze_response(
                question.question_text,
                response.transcript,
                json.loads(question.expected_criteria)
            )
            
            # Update response with analysis
            response.score = analysis.get('score', 0.0)
            response.analysis = analysis.get('analysis', '')
            
            db.commit()
            
    except Exception as e:
        print(f"Error in async response analysis: {e}")

async def complete_interview_analysis(interview_id: int, db: Session):
    """Complete final interview analysis."""
    try:
        from services.ai_service import AIService
        ai_service = AIService()
        
        # Get all responses for the interview
        responses = db.query(ResponseModel).filter(ResponseModel.interview_id == interview_id).all()
        
        if responses:
            # Prepare data for final analysis
            response_data = []
            for r in responses:
                response_data.append({
                    "question": r.question.question_text,
                    "transcript": r.transcript,
                    "score": r.score or 0.0
                })
            
            # Get final recommendation
            final_analysis = await ai_service.generate_final_recommendation(response_data)
            
            # Update interview record
            interview = db.query(Interview).filter(Interview.id == interview_id).first()
            interview.overall_score = final_analysis.get('overall_score', 0.0)
            interview.communication_score = final_analysis.get('communication_score', 0.0)
            interview.technical_score = final_analysis.get('technical_score', 0.0)
            interview.recommendation = final_analysis.get('recommendation', 'maybe')
            
            # Update candidate status
            candidate = db.query(Candidate).filter(Candidate.id == interview.candidate_id).first()
            candidate.status = "interviewed"
            
            db.commit()
            
    except Exception as e:
        print(f"Error in complete interview analysis: {e}")