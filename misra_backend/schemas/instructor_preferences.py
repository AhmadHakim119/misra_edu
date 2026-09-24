from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


ScenarioId = Literal[
    "valid_alternative_method",
    "minor_handwritten_syntax",
    "equivalent_notation",
    "carried_forward_error",
    "language_quality_outside_criterion",
]


SCENARIO_OPTIONS: dict[str, set[str]] = {
    "valid_alternative_method": {"full_credit", "partial_credit", "reject"},
    "minor_handwritten_syntax": {"full_credit", "minor_deduction", "reject"},
    "equivalent_notation": {"full_credit", "minor_deduction", "reject"},
    "carried_forward_error": {"single_penalty", "penalize_each", "criterion_specific"},
    "language_quality_outside_criterion": {"ignore", "minor_deduction", "assess"},
}


class InstructorExplicitPreferences(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method_credit: Literal["none", "partial", "full_if_valid"] | None = None
    handwritten_syntax_policy: Literal[
        "criterion_specific", "accept_unambiguous", "require_correct"
    ] | None = None
    notation_policy: Literal[
        "standard_required", "equivalent_allowed", "do_not_penalize"
    ] | None = None
    error_carried_forward: Literal[
        "criterion_specific", "single_penalty", "penalize_each"
    ] | None = None
    language_quality_policy: Literal[
        "criterion_specific", "ignore_unless_assessed", "assess"
    ] | None = None
    alternative_valid_methods: Literal[
        "criterion_specific", "allow", "disallow"
    ] | None = None


class InstructorScenarioAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: ScenarioId
    selected_option: str = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def option_belongs_to_scenario(self):
        if self.selected_option not in SCENARIO_OPTIONS[self.scenario_id]:
            choices = ", ".join(sorted(SCENARIO_OPTIONS[self.scenario_id]))
            raise ValueError(
                f"selected_option for {self.scenario_id} must be one of: {choices}"
            )
        return self


class InstructorPreferenceDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    explicit_preferences: InstructorExplicitPreferences = Field(
        default_factory=InstructorExplicitPreferences
    )
    scenario_answers: list[InstructorScenarioAnswer] = Field(
        default_factory=list, max_length=5
    )
    change_summary: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def require_unique_evidence(self):
        ids = [answer.scenario_id for answer in self.scenario_answers]
        if len(ids) != len(set(ids)):
            raise ValueError("Each calibration scenario can be answered only once.")
        explicit = self.explicit_preferences.model_dump(exclude_none=True)
        if not explicit and not self.scenario_answers:
            raise ValueError(
                "Provide at least one explicit preference or calibration scenario answer."
            )
        self.change_summary = self.change_summary.strip()
        return self


PreferenceReasonCode = Literal[
    "valid_alternative",
    "minor_notation",
    "method_credit",
    "carried_forward_error",
    "language_tolerance",
]


class PreferencePolicyProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alternative_methods_allowed: bool | None = None
    notation_policy: Literal[
        "standard_required", "equivalent_allowed", "do_not_penalize"
    ] | None = None
    method_credit: Literal["none", "partial", "full_if_valid"] | None = None
    error_carried_forward: Literal[
        "criterion_specific", "single_penalty", "penalize_each"
    ] | None = None
    language_quality_policy: Literal[
        "criterion_specific", "ignore_unless_assessed", "assess"
    ] | None = None


class PreferenceSuggestionProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["review_labels"] = "review_labels"
    review_reason_code: PreferenceReasonCode
    distinct_label_count: int = Field(ge=3)
    minimum_distinct_labels: int = Field(default=3, ge=3)
    derivation_version: Literal["review-v1"] = "review-v1"


class InstructorPreferenceSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_reason_code: PreferenceReasonCode
    distinct_label_count: int = Field(ge=3)
    source_label_ids: list[str] = Field(min_length=3)
    proposed_policy: PreferencePolicyProposal
    provenance: PreferenceSuggestionProvenance
    applies_automatically: Literal[False] = False


class InstructorPreferenceSuggestionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minimum_distinct_labels: int = Field(default=3, ge=3)
    suggestions: list[InstructorPreferenceSuggestion] = Field(default_factory=list)
    excluded_reason_codes: list[Literal[
        "rubric_issue", "ocr_or_mapping_error", "other"
    ]] = Field(
        default_factory=lambda: ["rubric_issue", "ocr_or_mapping_error", "other"]
    )
    applies_automatically: Literal[False] = False
