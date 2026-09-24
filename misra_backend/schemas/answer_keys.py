from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class AnswerKeyDocumentRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    job_id: str = Field(min_length=1, max_length=36)
    page_indices: list[Annotated[StrictInt, Field(ge=0)]] = Field(min_length=1, max_length=20)

    @model_validator(mode='after')
    def unique_pages(self):
        if len(self.page_indices) != len(set(self.page_indices)):
            raise ValueError('Select each reference page only once.')
        return self


class AnswerKeyDraftRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    mode: Literal['reference', 'no_fixed_answer'] = 'reference'
    reference_text: str = Field(default='', max_length=50000)
    acceptable_answers: list[Annotated[str, Field(min_length=1, max_length=10000)]] = Field(default_factory=list, max_length=100)
    document_refs: list[AnswerKeyDocumentRef] = Field(default_factory=list, max_length=5)
    change_summary: str = Field(default='', max_length=2000)

    @model_validator(mode='after')
    def coherent_reference(self):
        self.reference_text = self.reference_text.strip()
        self.acceptable_answers = [answer.strip() for answer in self.acceptable_answers]
        if any(not answer for answer in self.acceptable_answers):
            raise ValueError('Acceptable answers cannot be blank.')
        if len({ref.job_id for ref in self.document_refs}) != len(self.document_refs):
            raise ValueError('Combine page selections for each document into one reference.')
        if sum(len(ref.page_indices) for ref in self.document_refs) > 20:
            raise ValueError('Select at most 20 reference pages in total.')
        has_content = bool(self.reference_text or self.acceptable_answers or self.document_refs)
        if self.mode == 'no_fixed_answer' and has_content:
            raise ValueError('No fixed answer mode cannot contain reference answers or documents.')
        if self.mode == 'reference' and not has_content:
            raise ValueError('Provide reference text, an acceptable answer, or reference pages.')
        return self
