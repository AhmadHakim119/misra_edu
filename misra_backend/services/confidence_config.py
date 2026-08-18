from dataclasses import dataclass


@dataclass(frozen=True)
class ConfidenceConfig:
    needs_review_threshold: float = 70.0

    weight_ocr_legibility: float = 0.30
    weight_llm_confidence: float = 0.50
    weight_score_boundary: float = 0.20

    boundary_low: float = 0.40
    boundary_high: float = 0.60

    legibility_clear: float = 100.0
    legibility_partial: float = 60.0
    legibility_illegible: float = 10.0
    legibility_unknown: float = 50.0

    def legibility_map(self) -> dict[str, float]:
        return {
            "clear": self.legibility_clear,
            "partial": self.legibility_partial,
            "illegible": self.legibility_illegible,
        }


ACTIVE_CONFIG = ConfidenceConfig()