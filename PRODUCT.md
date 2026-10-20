# MISRA-EDU product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Instructors preparing assessments, marking written student work, and reviewing
AI suggestions. Individual-instructor use is the current pilot; institutional
administration is supported within existing tenant boundaries.

## Product Purpose

Make evidence-grounded assessment setup, extraction, grading and instructor
correction understandable in one workflow. The instructor owns marking decisions.

## Operating Context

Assessment first: approved questions, answer keys, rubric, scoring policy and
course references; then student upload, extraction, grading, review and export.
Course sources also support question drafts. The existing frontend remains
available while a parallel replacement is implemented in verified phases.

## Capabilities and Constraints

FastAPI, SQLAlchemy, MariaDB, Redis/RQ and static JavaScript. AI jobs run outside
the browser. Drafts do not authorize grading. Immutable runs preserve approved
inputs and evidence. Sources and student work are separate trust boundaries.
Question exceptions override assessment source defaults. Human score overrides
preserve original AI results. Confidence estimates are uncalibrated unless
supported by independent evaluation; no promise of error-free autonomous grading.
Existing assessments and approved marking rules must continue working.
No framework migration, billing or public deployment is part of this UI phase.

## Brand Commitments

MISRA-EDU. Professional, plain-language instructor workspace, not a chatbot.
Light and genuinely dark themes; responsive screens and native controls.

## Evidence on Hand

Implemented API contracts, synthetic backend and browser tests, and existing
workflows. Synthetic demonstration records must be labeled. Private papers and
evaluation labels are not public design assets or testimonials.

## Product Principles

- One obvious next action; explain what blocks it.
- AI proposes; approved definitions and instructor review control results.
- Show source work beside deductions and corrections.
- Saved state and job progress persist across navigation.
- Preserve the original workspace until feature parity is verified.
