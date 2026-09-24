"""Apply the additive grading-foundation upgrades to an existing database.

Back up the database before explicit execution. Each component upgrade is
idempotent; this coordinator does not create profiles, approve definitions,
regrade answers, or modify historical marks.
"""

from upgrade_answer_keys import main as upgrade_answer_keys
from upgrade_exam_setup import main as upgrade_exam_setup
from upgrade_instructor_preferences import main as upgrade_instructor_preferences
from upgrade_review_reasons import main as upgrade_review_reasons


def main() -> int:
    upgrades = (
        ("exam setup", upgrade_exam_setup),
        ("versioned answer keys", upgrade_answer_keys),
        ("instructor preference versions", upgrade_instructor_preferences),
        ("structured review reasons", upgrade_review_reasons),
    )
    for label, upgrade in upgrades:
        print(f"Applying {label} upgrade...")
        result = upgrade()
        if result not in (None, 0):
            raise RuntimeError(f"The {label} upgrade did not complete successfully.")
    print(
        "Grading foundations are ready. Existing rubrics, answers, grades, "
        "and review labels were not rewritten."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
