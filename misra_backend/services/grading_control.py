"""Cooperative stop checks for the grading worker and its provider calls."""
from contextvars import ContextVar


class GradingStopped(Exception):
    pass


grading_checkpoint = ContextVar('grading_checkpoint', default=None)
grading_stage = ContextVar('grading_stage', default=None)

# This progress reflects completed workflow stages, rather than elapsed time.
STAGE_PROGRESS = {'preparing': .05, 'assessing': .20, 'verifying': .65, 'saving': .90}


def report_grading_stage(stage):
    report = grading_stage.get()
    if report:
        report(stage)


def check_grading_active(*, lock=False):
    checkpoint = grading_checkpoint.get()
    if checkpoint:
        checkpoint(lock=lock)
