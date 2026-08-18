from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Question, QuestionGradingPolicy
from schemas.grading_policy_input import QuestionGradingPolicyRequest

router = APIRouter(prefix="/api", tags=["grading-policies"])


@router.get("/questions/{question_id}/grading-policy")
def get_grading_policy(question_id: str, db: Session = Depends(get_db)):
    policy = (
        db.query(QuestionGradingPolicy)
        .filter(QuestionGradingPolicy.question_id == question_id)
        .first()
    )
    if not policy:
        raise HTTPException(status_code=404, detail="No grading policy configured")
    return policy


@router.put("/questions/{question_id}/grading-policy")
def upsert_grading_policy(
    question_id: str,
    payload: QuestionGradingPolicyRequest,
    db: Session = Depends(get_db),
):
    question = db.query(Question).filter(Question.id == question_id).first()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    policy = (
        db.query(QuestionGradingPolicy)
        .filter(QuestionGradingPolicy.question_id == question_id)
        .first()
    )
    if not policy:
        policy = QuestionGradingPolicy(question_id=question_id)
        db.add(policy)

    for field, value in payload.model_dump().items():
        setattr(policy, field, value)

    db.commit()
    db.refresh(policy)
    return policy
