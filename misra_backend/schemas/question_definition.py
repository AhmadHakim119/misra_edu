"""Versioned question corrections stored with their marking-guide draft."""
from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Literal


class QuestionDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_number: str = Field(min_length=1, max_length=20)
    question_text: str = Field(min_length=1, max_length=20000)
    language: Literal['en', 'ar', 'mixed'] = 'mixed'

    @field_validator('question_number', 'question_text')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Question number and wording cannot be blank.')
        return value.strip()


class PreviousQuestionDefinition(BaseModel):
    model_config = ConfigDict(extra='forbid')
    question_number: str = Field(min_length=1, max_length=20)
    question_text: str = Field(max_length=20000)
    language: Literal['en', 'ar', 'mixed']


class QuestionDefinitionCorrection(QuestionDefinition):
    previous: PreviousQuestionDefinition
