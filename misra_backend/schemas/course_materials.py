from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

PageIndex = Annotated[StrictInt, Field(ge=0)]


class MaterialTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=255)
    text: str = Field(min_length=1, max_length=50000)

    @model_validator(mode="after")
    def nonblank(self):
        self.title, self.text = self.title.strip(), self.text.strip()
        if not self.title or not self.text:
            raise ValueError("Title and reference text cannot be blank.")
        return self


class MaterialPageEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=50000)
    printed_page_label: str | None = Field(default=None, max_length=30)
    expected_text_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class MaterialApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_indices: list[PageIndex] = Field(min_length=1, max_length=1000)
    confirm_content_reviewed: bool = False

    @model_validator(mode="after")
    def confirmed_pages(self):
        if len(set(self.page_indices)) != len(self.page_indices):
            raise ValueError("Select each reference page only once.")
        if not self.confirm_content_reviewed:
            raise ValueError("Review the selected pages, including equations, before approving.")
        return self


class MaterialBinding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(min_length=1, max_length=36)
    page_indices: list[PageIndex] = Field(min_length=1, max_length=1000)
    criterion_id: str | None = Field(default=None, min_length=1, max_length=100)
    chunk_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def unique_references(self):
        if len(set(self.page_indices)) != len(self.page_indices) or len(set(self.chunk_ids)) != len(self.chunk_ids):
            raise ValueError("Reference pages and passage IDs must be unique.")
        return self


class MaterialScopeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["required", "optional", "disabled", "inherit"] = "required"
    bindings: list[MaterialBinding] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def coherent_scope(self):
        if self.mode in {"disabled", "inherit"} and self.bindings:
            raise ValueError("Disabled or inherited retrieval cannot contain source bindings.")
        if self.mode not in {"disabled", "inherit"} and not self.bindings:
            raise ValueError("Select approved course-material pages for retrieval.")
        identities = [(b.version_id, b.criterion_id) for b in self.bindings]
        if len(identities) != len(set(identities)):
            raise ValueError("Combine duplicate source/criterion selections.")
        return self


class AssessmentMaterialScopeRequest(MaterialScopeRequest):
    mode: Literal["required", "optional", "disabled"] = "required"

    @model_validator(mode="after")
    def assessment_bindings(self):
        if any(binding.criterion_id is not None for binding in self.bindings):
            raise ValueError("Assessment defaults apply to all criteria. Use question exceptions for criterion-specific sources.")
        return self
