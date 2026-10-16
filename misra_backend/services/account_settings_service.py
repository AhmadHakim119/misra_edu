"""Persistent opt-out and defaults for newly created, unapproved guides only."""
from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy import inspect

from models import InstructorAccountSettings, InstructorPreferenceVersion
from schemas.rubric_v2 import RubricV2
from schemas.instructor_preferences import SCENARIO_OPTIONS


def require_settings_schema(db):
    if not inspect(db.connection()).has_table(InstructorAccountSettings.__tablename__):
        raise HTTPException(503, "Account settings need the account-settings database upgrade. Ask the local administrator to back up and apply it.")


def account_settings(db, user, *, lock=False):
    require_settings_schema(db)
    query = db.query(InstructorAccountSettings).filter_by(user_id=user.id, institution_id=user.institution_id)
    return (query.with_for_update().populate_existing() if lock else query).first()


def approved_profile(db, user):
    return db.query(InstructorPreferenceVersion).filter_by(
        user_id=user.id, institution_id=user.institution_id, status="approved"
    ).order_by(InstructorPreferenceVersion.version_number.desc()).first()


def public_settings(db, user):
    settings = account_settings(db, user)
    profile = approved_profile(db, user)
    return {
        "use_marking_preferences": settings.use_marking_preferences if settings else True,
        "has_approved_profile": profile is not None,
        "survey_completed": bool(profile and set(SCENARIO_OPTIONS).issubset({a.get('scenario_id') for a in profile.scenario_answers if isinstance(a, dict)})),
        "approved_profile_id": profile.id if profile else None,
    }


def apply_to_new_draft(db, user, rubric):
    """Called only when creating a new draft, never when loading or grading."""
    profile = approved_profile(db, user)
    if not profile:
        return rubric
    settings = account_settings(db, user)
    if settings and not settings.use_marking_preferences:
        return rubric
    value = deepcopy(rubric.model_dump() if isinstance(rubric, RubricV2) else rubric)
    policy = value.setdefault("policy", {})
    proposal = profile.derived_proposal or {}
    for key, item in proposal.items():
        if key == "custom_instructions":
            if item and item not in (policy.get(key) or ""):
                policy[key] = "\n".join(filter(None, [policy.get(key), item]))
        else:
            policy[key] = item
    return RubricV2.model_validate(value)
