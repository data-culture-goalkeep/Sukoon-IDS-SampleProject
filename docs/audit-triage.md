# Sensitive-value match triage

Review of the original 390 file/value findings (87 distinct values), with
line references updated for this PR. Each row below represents one finding;
identical rows can represent different matching values. No values are shown.

Classification 1 (coincidental numeric metadata/fixtures): 390;
classification 2 (schema/reference range): 0; classification 3 (copied source): 0.

All original matches are numeric. Context review located these numbers in
counts, timings, dates, versions, identifiers/digests, ports and invented test
fixtures, rather than copied workbook records. New handover/report metadata
is reviewed separately by the same exact-context rule. No value-wide exemption
exists. The production scanner checks every matching line, not only the first.

| File | Line | Field category | Classification |
|---|---:|---|---|
| config/approved-load-manifests.json | 3 | weight | 1 |
| config/approved-load-manifests.json | 3 | weight | 1 |
| config/approved-load-manifests.json | 3 | IQ | 1 |
| config/approved-load-manifests.json | 3 | weight | 1 |
| config/approved-load-manifests.json | 3 | IQ; weight | 1 |
| config/approved-load-manifests.json | 3 | IQ | 1 |
| config/approved-load-manifests.json | 3 | IQ | 1 |
| docs/fields.md | 576 | weight | 1 |
| docs/fields.md | 609 | IQ; weight | 1 |
| docs/fields.md | 38 | weight | 1 |
| docs/fields.md | 38 | weight | 1 |
| docs/fields.md | 111 | IQ; weight | 1 |
| docs/fields.md | 314 | weight | 1 |
| docs/fields.md | 297 | IQ; weight | 1 |
| docs/fields.md | 62 | IQ; weight | 1 |
| docs/fields.md | 186 | IQ; weight | 1 |
| docs/fields.md | 9 | IQ; weight | 1 |
| docs/fields.md | 314 | IQ | 1 |
| docs/fields.md | 609 | height | 1 |
| docs/fields.md | 576 | height | 1 |
| docs/handover.md | 229 | weight | 1 |
| docs/handover.md | 172 | IQ; weight | 1 |
| docs/handover.md | 530 | weight | 1 |
| docs/handover.md | 341 | weight | 1 |
| docs/handover.md | 437 | weight | 1 |
| docs/handover.md | 214 | IQ; weight | 1 |
| docs/handover.md | 172 | weight | 1 |
| docs/handover.md | 573 | weight | 1 |
| docs/handover.md | 341 | weight | 1 |
| docs/handover.md | 341 | IQ; weight | 1 |
| docs/handover.md | 664 | IQ; weight | 1 |
| docs/handover.md | 172 | IQ; weight | 1 |
| docs/handover.md | 244 | weight | 1 |
| docs/handover.md | 829 | IQ | 1 |
| docs/handover.md | 426 | IQ | 1 |
| docs/handover.md | 341 | weight | 1 |
| docs/handover.md | 172 | IQ; weight | 1 |
| docs/handover.md | 251 | weight | 1 |
| docs/handover.md | 172 | IQ; weight | 1 |
| docs/handover.md | 538 | IQ | 1 |
| docs/handover.md | 728 | IQ | 1 |
| docs/handover.md | 611 | IQ; weight | 1 |
| docs/handover.md | 172 | IQ; weight | 1 |
| docs/handover.md | 172 | weight | 1 |
| docs/handover.md | 341 | weight | 1 |
| docs/handover.md | 664 | IQ | 1 |
| docs/handover.md | 460 | weight | 1 |
| docs/handover.md | 510 | IQ; weight | 1 |
| docs/handover.md | 538 | IQ; weight | 1 |
| docs/handover.md | 247 | IQ | 1 |
| docs/handover.md | 460 | IQ; weight | 1 |
| docs/handover.md | 574 | IQ; weight | 1 |
| docs/handover.md | 510 | IQ | 1 |
| docs/handover.md | 740 | IQ | 1 |
| docs/handover.md | 426 | IQ | 1 |
| docs/handover.md | 438 | IQ | 1 |
| docs/handover.md | 460 | IQ | 1 |
| docs/handover.md | 453 | IQ | 1 |
| docs/handover.md | 538 | IQ; weight | 1 |
| docs/handover.md | 251 | IQ | 1 |
| docs/handover.md | 172 | IQ; weight | 1 |
| docs/handover.md | 172 | IQ | 1 |
| docs/handover.md | 1129 | IQ | 1 |
| docs/handover.md | 350 | IQ | 1 |
| docs/handover.md | 786 | IQ | 1 |
| docs/handover.md | 460 | IQ | 1 |
| docs/handover.md | 350 | IQ | 1 |
| docs/handover.md | 827 | IQ | 1 |
| docs/handover.md | 588 | IQ | 1 |
| docs/handover.md | 510 | IQ | 1 |
| docs/handover.md | 426 | IQ | 1 |
| docs/handover.md | 847 | IQ; weight | 1 |
| docs/handover.md | 805 | IQ | 1 |
| docs/handover.md | 611 | IQ | 1 |
| docs/handover.md | 510 | IQ | 1 |
| docs/handover.md | 829 | height | 1 |
| docs/handover.md | 437 | IQ | 1 |
| docs/handover.md | 728 | height | 1 |
| docs/handover.md | 784 | height | 1 |
| docs/handover.md | 172 | IQ | 1 |
| docs/handover.md | 861 | height | 1 |
| docs/handover.md | 906 | weight | 1 |
| docs/handover.md | 829 | height | 1 |
| docs/handover.md | 172 | IQ | 1 |
| docs/handover.md | 530 | height | 1 |
| docs/handover.md | 248 | height | 1 |
| docs/handover.md | 739 | weight | 1 |
| docs/model-spec.json | 41 | weight | 1 |
| docs/model-spec.json | 68 | IQ; weight | 1 |
| docs/model-spec.json | 512 | weight | 1 |
| docs/model-spec.json | 230 | weight | 1 |
| docs/model-spec.json | 548 | weight | 1 |
| docs/model-spec.json | 41 | IQ; weight | 1 |
| docs/model-spec.json | 169 | weight | 1 |
| docs/model-spec.json | 42 | weight | 1 |
| docs/model-spec.json | 350 | weight | 1 |
| docs/model-spec.json | 400 | IQ; weight | 1 |
| docs/model-spec.json | 512 | IQ; weight | 1 |
| docs/model-spec.json | 169 | IQ; weight | 1 |
| docs/model-spec.json | 513 | weight | 1 |
| docs/model-spec.json | 253 | IQ | 1 |
| docs/model-spec.json | 455 | IQ | 1 |
| docs/model-spec.json | 42 | weight | 1 |
| docs/model-spec.json | 124 | IQ; weight | 1 |
| docs/model-spec.json | 143 | weight | 1 |
| docs/model-spec.json | 253 | IQ; weight | 1 |
| docs/model-spec.json | 230 | IQ | 1 |
| docs/model-spec.json | 422 | IQ | 1 |
| docs/model-spec.json | 68 | IQ; weight | 1 |
| docs/model-spec.json | 284 | weight | 1 |
| docs/model-spec.json | 169 | weight | 1 |
| docs/model-spec.json | 207 | IQ | 1 |
| docs/model-spec.json | 101 | weight | 1 |
| docs/model-spec.json | 331 | IQ; weight | 1 |
| docs/model-spec.json | 101 | IQ; weight | 1 |
| docs/model-spec.json | 123 | IQ | 1 |
| docs/model-spec.json | 101 | IQ; weight | 1 |
| docs/model-spec.json | 9 | IQ; weight | 1 |
| docs/model-spec.json | 658 | IQ | 1 |
| docs/model-spec.json | 68 | IQ | 1 |
| docs/model-spec.json | 588 | IQ | 1 |
| docs/model-spec.json | 614 | height | 1 |
| docs/model-spec.json | 143 | IQ | 1 |
| docs/model-spec.json | 373 | IQ | 1 |
| docs/model-spec.json | 143 | IQ; weight | 1 |
| docs/model-spec.json | 253 | IQ | 1 |
| docs/model-spec.json | 41 | IQ | 1 |
| docs/model-spec.json | 10 | IQ; weight | 1 |
| docs/model-spec.json | 253 | IQ | 1 |
| docs/model-spec.json | 704 | IQ | 1 |
| docs/model-spec.json | 373 | height | 1 |
| docs/model-spec.json | 350 | IQ | 1 |
| docs/model-spec.json | 455 | IQ | 1 |
| docs/model-spec.json | 68 | IQ | 1 |
| docs/model-spec.json | 207 | IQ | 1 |
| docs/model-spec.json | 330 | IQ | 1 |
| docs/model-spec.json | 253 | IQ | 1 |
| docs/model-spec.json | 143 | IQ | 1 |
| docs/model-spec.json | 68 | IQ | 1 |
| docs/model-spec.json | 351 | IQ | 1 |
| docs/model-spec.json | 455 | IQ | 1 |
| docs/model-spec.json | 400 | IQ | 1 |
| docs/model-spec.json | 41 | height | 1 |
| docs/model-spec.json | 480 | IQ | 1 |
| docs/model-spec.json | 350 | height | 1 |
| docs/model-spec.json | 253 | height | 1 |
| docs/model-spec.json | 9 | IQ | 1 |
| docs/model.md | 242 | weight | 1 |
| docs/model.md | 148 | IQ; weight | 1 |
| docs/model.md | 149 | weight | 1 |
| docs/model.md | 161 | weight | 1 |
| docs/model.md | 242 | IQ; weight | 1 |
| docs/model.md | 242 | weight | 1 |
| docs/model.md | 237 | IQ | 1 |
| docs/model.md | 148 | height | 1 |
| docs/runbook.md | 307 | weight | 1 |
| docs/runbook.md | 45 | weight | 1 |
| docs/runbook.md | 307 | weight | 1 |
| docs/runbook.md | 45 | IQ | 1 |
| docs/runbook.md | 160 | IQ | 1 |
| docs/runbook.md | 311 | IQ | 1 |
| docs/source-audit-v2.json | 2 | weight | 1 |
| docs/source-audit-v2.json | 76 | IQ; weight | 1 |
| docs/source-audit-v2.json | 342 | weight | 1 |
| docs/source-audit-v2.json | 105 | weight | 1 |
| docs/source-audit-v2.json | 44 | weight | 1 |
| docs/source-audit-v2.json | 48 | IQ; weight | 1 |
| docs/source-audit-v2.json | 8 | weight | 1 |
| docs/source-audit-v2.json | 49 | weight | 1 |
| docs/source-audit-v2.json | 44 | weight | 1 |
| docs/source-audit-v2.json | 415 | IQ; weight | 1 |
| docs/source-audit-v2.json | 72 | IQ; weight | 1 |
| docs/source-audit-v2.json | 105 | IQ; weight | 1 |
| docs/source-audit-v2.json | 128 | weight | 1 |
| docs/source-audit-v2.json | 105 | IQ | 1 |
| docs/source-audit-v2.json | 105 | IQ | 1 |
| docs/source-audit-v2.json | 44 | weight | 1 |
| docs/source-audit-v2.json | 52 | IQ; weight | 1 |
| docs/source-audit-v2.json | 128 | weight | 1 |
| docs/source-audit-v2.json | 105 | IQ; weight | 1 |
| docs/source-audit-v2.json | 176 | IQ | 1 |
| docs/source-audit-v2.json | 149 | IQ | 1 |
| docs/source-audit-v2.json | 76 | IQ; weight | 1 |
| docs/source-audit-v2.json | 176 | IQ; weight | 1 |
| docs/source-audit-v2.json | 105 | weight | 1 |
| docs/source-audit-v2.json | 10 | weight | 1 |
| docs/source-audit-v2.json | 72 | IQ | 1 |
| docs/source-audit-v2.json | 109 | weight | 1 |
| docs/source-audit-v2.json | 72 | IQ; weight | 1 |
| docs/source-audit-v2.json | 109 | IQ; weight | 1 |
| docs/source-audit-v2.json | 128 | IQ | 1 |
| docs/source-audit-v2.json | 1091 | IQ | 1 |
| docs/source-audit-v2.json | 109 | IQ; weight | 1 |
| docs/source-audit-v2.json | 15 | IQ; weight | 1 |
| docs/source-audit-v2.json | 19 | IQ | 1 |
| docs/source-audit-v2.json | 76 | IQ | 1 |
| docs/source-audit-v2.json | 738 | IQ | 1 |
| docs/source-audit-v2.json | 176 | IQ | 1 |
| docs/source-audit-v2.json | 629 | height | 1 |
| docs/source-audit-v2.json | 149 | IQ | 1 |
| docs/source-audit-v2.json | 105 | IQ | 1 |
| docs/source-audit-v2.json | 72 | IQ | 1 |
| docs/source-audit-v2.json | 72 | IQ; weight | 1 |
| docs/source-audit-v2.json | 6 | IQ | 1 |
| docs/source-audit-v2.json | 48 | IQ | 1 |
| docs/source-audit-v2.json | 16 | IQ; weight | 1 |
| docs/source-audit-v2.json | 72 | IQ | 1 |
| docs/source-audit-v2.json | 732 | IQ | 1 |
| docs/source-audit-v2.json | 2 | IQ | 1 |
| docs/source-audit-v2.json | 391 | height | 1 |
| docs/source-audit-v2.json | 10 | IQ | 1 |
| docs/source-audit-v2.json | 105 | IQ | 1 |
| docs/source-audit-v2.json | 8 | IQ | 1 |
| docs/source-audit-v2.json | 733 | IQ | 1 |
| docs/source-audit-v2.json | 76 | IQ | 1 |
| docs/source-audit-v2.json | 1181 | height | 1 |
| docs/source-audit-v2.json | 72 | IQ | 1 |
| docs/source-audit-v2.json | 219 | IQ | 1 |
| docs/source-audit-v2.json | 735 | IQ | 1 |
| docs/source-audit-v2.json | 136 | height | 1 |
| docs/source-audit-v2.json | 128 | IQ | 1 |
| docs/source-audit-v2.json | 267 | IQ | 1 |
| docs/source-audit-v2.json | 363 | IQ; weight | 1 |
| docs/source-audit-v2.json | 153 | IQ | 1 |
| docs/source-audit-v2.json | 599 | height | 1 |
| docs/source-audit-v2.json | 149 | height | 1 |
| docs/source-audit-v2.json | 76 | IQ | 1 |
| docs/source-audit-v2.json | 215 | IQ | 1 |
| docs/source-audit-v2.json | 263 | IQ | 1 |
| docs/source-audit-v2.json | 967 | height | 1 |
| docs/source-audit-v2.json | 10 | IQ | 1 |
| docs/source-audit-v2.json | 759 | height | 1 |
| docs/source-audit-v2.json | 559 | height | 1 |
| docs/source-audit-v2.json | 48 | height | 1 |
| docs/source-audit-v2.json | 176 | height | 1 |
| docs/source-audit-v2.json | 559 | height | 1 |
| docs/source-audit-v2.json | 105 | IQ | 1 |
| docs/source-audit-v2.json | 367 | height | 1 |
| docs/source-audit-v2.json | 753 | height | 1 |
| docs/source-audit-v2.json | 267 | height | 1 |
| docs/source-audit-v2.json | 15 | IQ | 1 |
| docs/source-audit-v2.json | 1354 | height | 1 |
| docs/source-audit-v2.json | 752 | height | 1 |
| docs/source-audit-v2.json | 1010 | height | 1 |
| docs/source-audit-v2.json | 387 | height | 1 |
| docs/source-audit-v2.json | 751 | height | 1 |
| docs/validation.md | 10 | weight | 1 |
| docs/validation.md | 164 | IQ; weight | 1 |
| docs/validation.md | 19 | weight | 1 |
| docs/validation.md | 84 | weight | 1 |
| docs/validation.md | 156 | weight | 1 |
| docs/validation.md | 39 | IQ; weight | 1 |
| docs/validation.md | 10 | weight | 1 |
| docs/validation.md | 227 | weight | 1 |
| docs/validation.md | 84 | weight | 1 |
| docs/validation.md | 84 | IQ; weight | 1 |
| docs/validation.md | 318 | IQ; weight | 1 |
| docs/validation.md | 49 | IQ; weight | 1 |
| docs/validation.md | 380 | weight | 1 |
| docs/validation.md | 477 | IQ | 1 |
| docs/validation.md | 553 | IQ | 1 |
| docs/validation.md | 39 | weight | 1 |
| docs/validation.md | 39 | IQ; weight | 1 |
| docs/validation.md | 39 | weight | 1 |
| docs/validation.md | 268 | IQ; weight | 1 |
| docs/validation.md | 192 | IQ | 1 |
| docs/validation.md | 382 | IQ | 1 |
| docs/validation.md | 265 | IQ; weight | 1 |
| docs/validation.md | 448 | IQ; weight | 1 |
| docs/validation.md | 49 | weight | 1 |
| docs/validation.md | 84 | weight | 1 |
| docs/validation.md | 318 | IQ | 1 |
| docs/validation.md | 39 | weight | 1 |
| docs/validation.md | 39 | IQ; weight | 1 |
| docs/validation.md | 192 | IQ; weight | 1 |
| docs/validation.md | 477 | IQ | 1 |
| docs/validation.md | 39 | IQ; weight | 1 |
| docs/validation.md | 228 | IQ; weight | 1 |
| docs/validation.md | 164 | IQ | 1 |
| docs/validation.md | 394 | IQ | 1 |
| docs/validation.md | 192 | IQ | 1 |
| docs/validation.md | 39 | IQ | 1 |
| docs/validation.md | 318 | IQ | 1 |
| docs/validation.md | 372 | IQ | 1 |
| docs/validation.md | 97 | IQ; weight | 1 |
| docs/validation.md | 355 | IQ | 1 |
| docs/validation.md | 51 | IQ; weight | 1 |
| docs/validation.md | 39 | IQ | 1 |
| docs/validation.md | 10 | IQ | 1 |
| docs/validation.md | 142 | height | 1 |
| docs/validation.md | 440 | IQ | 1 |
| docs/validation.md | 561 | IQ | 1 |
| docs/validation.md | 10 | IQ | 1 |
| docs/validation.md | 475 | IQ | 1 |
| docs/validation.md | 242 | IQ | 1 |
| docs/validation.md | 164 | IQ | 1 |
| docs/validation.md | 495 | IQ; weight | 1 |
| docs/validation.md | 459 | IQ | 1 |
| docs/validation.md | 265 | IQ | 1 |
| docs/validation.md | 164 | IQ | 1 |
| docs/validation.md | 39 | IQ | 1 |
| docs/validation.md | 477 | height | 1 |
| docs/validation.md | 440 | IQ | 1 |
| docs/validation.md | 382 | height | 1 |
| docs/validation.md | 438 | height | 1 |
| docs/validation.md | 192 | IQ | 1 |
| docs/validation.md | 509 | height | 1 |
| docs/validation.md | 554 | weight | 1 |
| docs/validation.md | 477 | height | 1 |
| docs/validation.md | 84 | IQ | 1 |
| docs/validation.md | 19 | height | 1 |
| docs/validation.md | 393 | weight | 1 |
| scripts/audit_ids_diff.py | 119 | weight | 1 |
| scripts/audit_ids_diff.py | 117 | weight | 1 |
| scripts/ids_runner.py | 205 | IQ; weight | 1 |
| scripts/ids_runner.py | 67 | weight | 1 |
| scripts/ids_runner.py | 43 | IQ | 1 |
| scripts/ids_runner.py | 83 | weight | 1 |
| scripts/ids_runner.py | 298 | IQ | 1 |
| scripts/ids_runner.py | 216 | IQ | 1 |
| scripts/load_ids.py | 261 | weight | 1 |
| scripts/load_ids.py | 503 | IQ; weight | 1 |
| scripts/load_ids.py | 260 | IQ | 1 |
| scripts/load_ids.py | 83 | weight | 1 |
| scripts/load_ids.py | 363 | IQ; weight | 1 |
| scripts/load_ids.py | 32 | weight | 1 |
| scripts/load_ids.py | 363 | IQ; weight | 1 |
| scripts/load_ids.py | 31 | IQ | 1 |
| scripts/load_ids.py | 127 | IQ; weight | 1 |
| scripts/load_ids.py | 283 | IQ | 1 |
| scripts/load_ids.py | 503 | height | 1 |
| scripts/load_ids.py | 127 | IQ | 1 |
| scripts/load_ids.py | 127 | IQ | 1 |
| supabase/migrations/20261114104958_align_goal_review_scales.sql | 4 | weight | 1 |
| tests/review_regressions.sql | 17 | weight | 1 |
| tests/review_regressions.sql | 17 | weight | 1 |
| tests/review_regressions.sql | 17 | IQ; weight | 1 |
| tests/review_regressions.sql | 15 | weight | 1 |
| tests/review_regressions.sql | 16 | weight | 1 |
| tests/review_regressions.sql | 27 | weight | 1 |
| tests/review_regressions.sql | 19 | IQ; weight | 1 |
| tests/review_regressions.sql | 17 | IQ; weight | 1 |
| tests/review_regressions.sql | 19 | IQ; weight | 1 |
| tests/review_regressions.sql | 23 | IQ | 1 |
| tests/review_regressions.sql | 15 | IQ | 1 |
| tests/schema_contract.sql | 48 | IQ; weight | 1 |
| tests/schema_contract.sql | 49 | weight | 1 |
| tests/schema_contract.sql | 112 | IQ; weight | 1 |
| tests/schema_contract.sql | 84 | IQ | 1 |
| tests/schema_contract.sql | 111 | weight | 1 |
| tests/schema_contract.sql | 61 | weight | 1 |
| tests/schema_contract.sql | 112 | IQ; weight | 1 |
| tests/schema_contract.sql | 102 | IQ; weight | 1 |
| tests/schema_contract.sql | 110 | IQ | 1 |
| tests/schema_contract.sql | 83 | IQ | 1 |
| tests/schema_contract.sql | 102 | IQ | 1 |
| tests/schema_contract.sql | 83 | IQ; weight | 1 |
| tests/schema_contract.sql | 48 | height | 1 |
| tests/test_ids_runner.py | 60 | weight | 1 |
| tests/test_ids_runner.py | 229 | IQ; weight | 1 |
| tests/test_ids_runner.py | 44 | weight | 1 |
| tests/test_ids_runner.py | 60 | IQ | 1 |
| tests/test_load_ids.py | 114 | weight | 1 |
| tests/test_load_ids.py | 26 | weight | 1 |
| tests/test_load_ids.py | 26 | IQ; weight | 1 |
| tests/test_load_ids.py | 26 | weight | 1 |
| tests/test_load_ids.py | 179 | IQ | 1 |
| tests/test_load_ids.py | 20 | IQ; weight | 1 |
| tests/test_load_ids.py | 137 | IQ | 1 |
| tests/test_load_ids.py | 20 | IQ | 1 |
| tests/test_load_ids.py | 114 | IQ | 1 |
| tests/test_load_ids.py | 136 | IQ | 1 |
| tests/test_load_ids.py | 136 | IQ | 1 |
| tests/test_loader_integration.py | 15 | IQ; weight | 1 |
| tests/test_loader_integration.py | 15 | weight | 1 |
| tests/test_loader_integration.py | 15 | weight | 1 |
| tests/test_loader_integration.py | 15 | IQ; weight | 1 |
| tests/test_loader_integration.py | 15 | weight | 1 |
| tests/test_loader_integration.py | 15 | weight | 1 |
| tests/test_loader_integration.py | 15 | IQ; weight | 1 |
| tests/test_loader_integration.py | 15 | IQ; weight | 1 |
| tests/test_loader_integration.py | 15 | IQ | 1 |
| tests/test_loader_integration.py | 66 | IQ | 1 |
| tests/test_loader_integration.py | 20 | IQ | 1 |
| tests/test_loader_integration.py | 15 | IQ | 1 |
| tests/test_loader_integration.py | 15 | IQ | 1 |
| tests/test_loader_integration.py | 308 | height | 1 |
| tests/test_worker_requests.py | 62 | weight | 1 |
| tests/test_worker_requests.py | 29 | IQ | 1 |
| tests/test_worker_requests.py | 62 | IQ | 1 |
