# Requirements Coverage Matrix

Status: **S03 complete (2026-09-06)**. This matrix now records post-S03
behavior: the output-tolerance rule is wired UNKNOWN-first, thermal and
peak-fallback qualification use structured cooling-regime matching, and
requirement-field-to-rule coverage is machine-enforced. The pre-S03 frozen
baseline version of this document is preserved in git history (commit
`02df2a9`, "WIP: complete S02 and start S03 rule coverage").

This document does not claim that an existing rule is sufficient merely
because a requirement field is passed into a function.

## 1. Formal qualification rule set

Current DEFAULT_REQUIRED_RULE_IDS:

| Rule ID | Current role |
|---|---|
| `vin.range` | Recommended operating input-voltage range |
| `vout.range` | Output-voltage operating range at minimum VIN |
| `vout.tolerance` | Output-voltage tolerance requirement; UNKNOWN-first until a structured worst-case total-error capability exists |
| `iout.continuous` | Continuous output-current rating |
| `iout.peak` | Peak current and duration, with continuous-rating fallback gated by cooling regime and ambient |
| `surge.input` | Input-surge knowledge / current transient-model boundary |
| `thermal.ambient` | Ambient-temperature rating with structural cooling-regime applicability matching |

## 2. Requirement coverage matrix

| RequirementCard field | Unit / state | Hard requirement role | Current rule / gate | Product data currently used | Evidence currently required | Current behavior | Uncovered or unsafe boundary | Required state while uncovered |
|---|---|---|---|---|---|---|---|---|
| `raw_request` | text | Context / audit input, not a technical hard rule | Requirement parsing only | None | None | Preserved as user wording | No independent screening rule required | N/A |
| `vin_min_v` | V | Hard operating requirement | `vin.range`; also used by `vout.range` | `vin_min_v`, `vin_max_v`; VOUT ratio if present | Evidence for VIN min/max; VOUT evidence separately | Range can PASS/FAIL/UNKNOWN | Current rule covers requested minimum VIN | Existing rule state |
| `vin_nominal_v` | V | Context plus relationship validation | RequirementCard validation only | None directly | None directly | Must lie between requested VIN min/max | Collected but intentionally not an independent hard-rule decision in current design | N/A unless a later product capability specifically depends on nominal VIN |
| `vin_max_v` | V | Hard operating requirement | `vin.range` | `vin_min_v`, `vin_max_v` | Evidence for VIN min/max | Range can PASS/FAIL/UNKNOWN | Current rule covers requested maximum VIN | Existing rule state |
| `surge_knowledge` | `PRESENT` / `NONE_EXPECTED` / `UNKNOWN` | Hard qualification input | `surge.input` | Normal `vin_max_v`; Absolute Maximum only shown as non-qualifying context | Normal VIN evidence when no surge is expected | `NONE_EXPECTED` may PASS; `PRESENT` is UNKNOWN; explicit unknown is UNKNOWN | No transient capability model exists | `UNKNOWN` for PRESENT or unknown surge |
| `surge_voltage_v` | V | Hard transient requirement when surge is PRESENT | `surge.input` | No qualifying transient product field | No qualifying transient evidence model | Collected and displayed; PRESENT remains UNKNOWN | Cannot infer transient PASS from Absolute Maximum VIN | `UNKNOWN` |
| `surge_duration_ms` | ms | Hard transient requirement when surge is PRESENT | `surge.input` | No qualifying transient product field | No qualifying transient evidence model | Collected and displayed; PRESENT remains UNKNOWN | Waveform, repetition, protection and operating conditions are not modeled | `UNKNOWN` |
| `vout_target_v` | V | Hard operating requirement | `vout.range` | `vout_min_v`, `vout_max_v`, `vout_max_vin_ratio` | Evidence for lower and applicable upper bounds | PASS/FAIL/UNKNOWN at requested minimum VIN | Voltage range does not prove output accuracy | Existing rule state |
| `vout_tolerance_percent` | % | Hard output-accuracy requirement | `vout.tolerance` (emitted by screening since S03) | None: no structured total-output-error capability; feedback-reference accuracy is not treated as total accuracy | No structured accuracy evidence | Always UNKNOWN with a deterministic reason; never inferred from the `vout.range` PASS | Worst-case total output error is not calculated from error sources | `UNKNOWN` |
| `iout_continuous_a` | A | Hard load requirement | `iout.continuous` | `iout_continuous_max_a` | Evidence for continuous-current rating | PASS/FAIL/UNKNOWN | Rating applicability conditions are not structured in the current product model | Existing rule is usable only within supported evidence applicability; unresolved conditions must not be generalized |
| `iout_peak_a` | A | Hard peak-load requirement | `iout.peak` | `iout_peak_max_a`, `iout_peak_duration_max_ms`; or continuous-current fallback | Peak-current and duration evidence; or continuous-current evidence for fallback | Explicit peak path PASS/FAIL/UNKNOWN; fallback PASS only when the rating regime is stated and matches the requested regime | Continuous-rating fallback cannot generalize to an unstated or mismatched cooling regime | `UNKNOWN` when fallback applicability is not established |
| `peak_duration_ms` | ms | Hard peak-duration requirement | `iout.peak` | `iout_peak_duration_max_ms`; ignored when continuous-current fallback is used | Duration evidence for explicit peak rating | Explicit peak path compares duration | Continuous fallback treats continuous rating as stronger, but does not prove that its conditions match the requested operating point | `UNKNOWN` when fallback applicability is not established |
| `ambient_max_c` | degC | Hard thermal requirement | `thermal.ambient` | `ambient_temp_max_c`; `ambient_cooling_method` (rating regime) | Evidence for explicit ambient-temperature rating | Numeric PASS only when the rating regime is stated and structurally covers the requested regime | A numeric rating alone does not prove the requested cooling regime | `UNKNOWN` when the user regime or the rating regime is unstated, or regimes are incompatible |
| `cooling_method` | `NATURAL_CONVECTION` / `FORCED_AIRFLOW` / null | Structural applicability condition (S03) | `thermal.ambient`; regime gate for the `iout.peak` continuous-rating fallback | `ambient_cooling_method`, `iout_continuous_cooling_method` | Same evidence as the consuming numeric rule | Natural-convection rating covers natural-convection and (at equal or lower numbers) forced-airflow requests; forced-airflow rating qualifies forced-airflow requests only | Unstated user regime or unstated rating regime cannot be extended to any regime | `UNKNOWN` |
| `thermal_conditions` | text today | Context / process-only (S03) | Explicitly declared context-only in `REQUIREMENT_FIELD_COVERAGE`; replaced by the structured `cooling_method` field | None | None | Preserved for traceability; does not affect PASS/FAIL | Free text must not become the decision input for thermal qualification | N/A (structurally covered by `cooling_method`) |
| `confirmed_by_user` | boolean | Process gate, not a product capability | `evaluate_candidate` precondition | None | None | Screening is rejected unless requirements are confirmed | Must remain separate from engineering qualification | Gate failure, not rule PASS/FAIL |

## 3. Current rule-to-field consumption

| Rule / gate | Requirement fields actually consumed |
|---|---|
| RequirementCard relationship validation | `vin_min_v`, `vin_nominal_v`, `vin_max_v`, `iout_continuous_a`, `iout_peak_a`, surge fields |
| Screening confirmation gate | `confirmed_by_user` |
| `vin.range` | `vin_min_v`, `vin_max_v` |
| `vout.range` | `vout_target_v`, `vin_min_v` |
| `vout.tolerance` | `vout_tolerance_percent` |
| `iout.continuous` | `iout_continuous_a` |
| `iout.peak` | `iout_peak_a`, `peak_duration_ms`, `cooling_method` (fallback regime gate), `ambient_max_c` (fallback ambient gate) |
| `surge.input` | `surge_knowledge`, `surge_voltage_v`, `surge_duration_ms` |
| `thermal.ambient` | `ambient_max_c`, `cooling_method` |
| No hard rule | none: every requirement field has a declared disposition in `REQUIREMENT_FIELD_COVERAGE` |

Passing a field into a function is not by itself proof that the field affects
qualification. Since S03 the declared dispositions are machine-enforced: every
`RequirementCard` field name and every referenced rule ID must appear in
`REQUIREMENT_FIELD_COVERAGE` (`src/local_chip_advisor/screening.py`) and the
guard test `tests/test_screening_coverage.py` fails when a collected
requirement field is silently consumed by no rule.

## 4. S03 gap resolutions

### G03-1: Output tolerance — resolved

`vout_tolerance_percent` now has a dedicated rule entry point,
`check_output_tolerance`, emitted by screening and listed in
`DEFAULT_REQUIRED_RULE_IDS` (7 rules). Safety behavior implemented and locked:

- no structured product total-output-error capability -> UNKNOWN;
- no decisive reviewed accuracy evidence -> UNKNOWN;
- output-voltage range evidence alone cannot satisfy the rule;
- feedback-reference accuracy alone cannot be treated as total output accuracy;
- the rule is UNKNOWN-only: no present capability ever yields PASS, so a
  formal candidate can no longer ignore the requested tolerance.

Regression coverage: unit tests in `tests/test_product_rules.py`,
screening-level binding tests in `tests/test_screening.py`, and issue
surfacing tests in `tests/test_recommendation.py`.

### G03-2: Thermal applicability — resolved

`thermal_conditions` is no longer a decision input that a PASS could ignore.
S03 introduced a structured cooling regime:

- `ThermalCoolingMode` (`NATURAL_CONVECTION` / `FORCED_AIRFLOW`) on the
  requirement card (`RequirementCard.cooling_method`) and on the product
  record (`ambient_cooling_method`);
- `check_ambient_thermal` now requires a matched regime: a natural-convection
  rating covers natural-convection requests and, at equal or lower numbers,
  forced-airflow requests; a forced-airflow rating qualifies forced-airflow
  requests only; an unstated user regime or unstated rating regime yields
  UNKNOWN — a numeric ambient rating alone cannot PASS and FAIL never crosses
  regimes;
- `thermal_conditions` free text is declared context/process-only and is kept
  for traceability.

### G03-3: Peak-current applicability — resolved

The continuous-current fallback inside `check_peak_output_current` no longer
grants PASS by rating magnitude alone. It now requires:

- the requested cooling regime (`cooling_method`) and the rating regime
  (`iout_continuous_cooling_method`); unstated regime on either side, or a
  forced-airflow rating facing a natural-convection request, yields UNKNOWN;
- within a matched regime, the requested ambient temperature
  (`requested_ambient_max_c`) must not exceed the rating's stated ambient.

The explicit peak path still requires current and duration evidence.

### G03-4: Surge boundary — retained

The conservative boundary is unchanged and regression-locked:

- `PRESENT` surge -> UNKNOWN until a qualified transient model exists;
- `UNKNOWN` surge -> UNKNOWN;
- Absolute Maximum VIN is not a normal transient operating capability;
- `NONE_EXPECTED` is distinct from unknown.

Seven regression tests lock this boundary; S03 does not weaken it.

## 5. Coverage invariant for future requirement fields

Every requirement field that can affect formal engineering qualification must
have an explicit disposition:

1. consumed by one or more hard rules;
2. consumed as a structural applicability condition of a hard rule; or
3. explicitly classified as context / process-only and documented as such.

A field may not be required for user confirmation and then silently disappear
from formal screening. Since S03 this invariant is enforced automatically:
`REQUIREMENT_FIELD_COVERAGE` in `screening.py` declares a disposition for
every field, and `tests/test_screening_coverage.py` fails when the declared
keys deviate from `RequirementCard.model_fields` or the declared rule IDs
deviate from `DEFAULT_REQUIRED_RULE_IDS`.

## 6. S03 implementation order — completed

1. Freeze the baseline matrix (git commit `02df2a9`).
2. Add the output-tolerance rule with UNKNOWN-first behavior.
3. Add that rule to screening and `DEFAULT_REQUIRED_RULE_IDS`.
4. Add a coverage test for collected hard requirements.
5. Introduce structured thermal applicability and prevent numeric-only PASS.
6. Tighten the continuous-current fallback used by `iout.peak`.
7. Re-run formal-classification regression tests, including:
   - requested +/-2 percent with no accuracy evidence -> not FORMAL;
   - sufficient ambient temperature but unresolved natural-convection
     applicability -> not FORMAL;
   - Absolute Maximum VIN alone -> never surge PASS.

Final regression: **212 passed**. No existing published product or evidence
review state was changed by S03.
