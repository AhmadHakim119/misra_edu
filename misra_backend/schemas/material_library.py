from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class ChapterBoundary(BaseModel):
    model_config = ConfigDict(extra='forbid')
    title: str = Field(min_length=1,max_length=255)
    start_page: StrictInt = Field(ge=1,le=1000)
    end_page: StrictInt = Field(ge=1,le=1000)

    @model_validator(mode='after')
    def valid_range(self):
        self.title=self.title.strip()
        if not self.title or self.end_page<self.start_page:
            raise ValueError('Enter a chapter title and a valid document page range.')
        return self


class ChapterIndexRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    chapters: list[ChapterBoundary] = Field(min_length=1,max_length=150)
    expected_text_fingerprint: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirm_boundaries_reviewed: bool = False

    @model_validator(mode='after')
    def reviewed(self):
        if not self.confirm_boundaries_reviewed:
            raise ValueError('Check chapter boundaries against the original before saving.')
        return self
