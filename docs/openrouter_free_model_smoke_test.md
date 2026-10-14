# OpenRouter free-model smoke test (2026-09-24)

This test sent three invented answers (SQL, arithmetic, ethics) to free
OpenRouter model endpoints. No student paper, student identity, database row,
or institutional document was sent. It did not change any MISRA grade.

| Endpoint | Result |
| --- | --- |
| `nvidia/nemotron-3-super-120b-a12b:free` | 3/3 valid MISRA grading responses after reasoning was disabled; all three illustrative scores matched the hand-written synthetic expectations. Individual request latency: 2.6 s, 3.8 s, 4.2 s. |
| `google/gemma-4-31b-it:free` | HTTP 429 for the attempted synthetic requests; no grade returned. |
| `google/gemma-4-26b-a4b-it:free` | HTTP 429; no grade returned. |
| `deepseek/deepseek-r1:free` | HTTP 404; this free slug was unavailable for this account at test time. |

The first Nemotron request returned an empty completion while reasoning was
enabled. Disabling reasoning and allowing a larger response budget produced
valid JSON that passed MISRA's score-total, criterion-ID, and evidence-reference
validation. The client uses the exact `:free` slug and cannot silently choose a
paid model.

These three invented examples are a contract and availability check, **not**
evidence of grading accuracy. Before selecting a grading provider, run a
separate benchmark on a diverse, instructor-labelled, held-out set, including
Arabic and English answers, visual evidence, partial credit, and OCR errors.
Record provider/model identifiers, invalid responses, latency, and review
decisions. Check provider data handling before sending identifiable student
work. Free endpoint availability and limits can change without notice.
