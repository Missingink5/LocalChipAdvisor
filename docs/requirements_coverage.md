# Requirements Coverage Matrix

Status: S03 baseline derived from the current RequirementCard, product model,
screening entry points, rule implementations, and DEFAULT_REQUIRED_RULE_IDS.

This document records current behavior before S03 rule changes. It does not
claim that an existing rule is sufficient merely because a requirement field
is passed into a function.

## 1. Formal qualification rule set

Current DEFAULT_REQUIRED_RULE_IDS:

| Rule ID | Current role |
|---|---|
| `vin.range` | Recommended operating input-voltage range |
| `vout.range` | Output-voltage operating range at minimum VIN |
| `iout.continuous` | Continuous output-current rating |
| `iout.peak` | Peak current and duration, with continuous-rating fallback |
| `surge.input` | Input-surge knowledge / current transient-model boundary |
| `thermal.ambient` | Ambient-temperature rating |

Current formal rule set has no output-tolerance rule.

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
| `vout_tolerance_percent` | % | Hard output-accuracy requirement | **No rule currently consumes this field** | No structured total-output-error capability | No structured accuracy evidence | Required for confirmation but absent from screening checks | A formal candidate can currently ignore requested tolerance | **Must become `UNKNOWN` until a dedicated rule and decisive evidence exist** |
| `iout_continuous_a` | A | Hard load requirement | `iout.continuous` | `iout_continuous_max_a` | Evidence for continuous-current rating | PASS/FAIL/UNKNOWN | Rating applicability conditions are not structured in the current product model | Existing rule is usable only within supported evidence applicability; unresolved conditions must not be generalized |
| `iout_peak_a` | A | Hard peak-load requirement | `iout.peak` | `iout_peak_max_a`, `iout_peak_duration_max_ms`; or continuous-current fallback | Peak-current and duration evidence; or continuous-current evidence for fallback | PASS/FAIL/UNKNOWN | Continuous-rating fallback currently ignores voltage, temperature, PCB, airflow and similar applicability conditions | **Must not PASS via fallback when applicable operating conditions are unproven** |
| `peak_duration_ms` | ms | Hard peak-duration requirement | `iout.peak` | `iout_peak_duration_max_ms`; ignored when continuous-current fallback is used | Duration evidence for explicit peak rating | Explicit peak path compares duration | Continuous fallback treats continuous rating as stronger, but does not prove that its conditions match the requested operating point | `UNKNOWN` when fallback applicability is not established |
| `ambient_max_c` | degC | Hard thermal requirement | `thermal.ambient` | `ambient_temp_max_c` | Evidence for explicit ambient-temperature rating | PASS/FAIL/UNKNOWN from numeric ambient rating | Numeric ambient rating alone does not prove requested cooling / PCB / load conditions | Must not be formal when thermal applicability is unproven |
| `thermal_conditions` | text today | Hard applicability condition | Passed to `thermal.ambient`, but **not structurally matched** | No structured cooling / PCB / airflow / power applicability fields | Only ambient-temperature evidence is currently used | Text is included in the requirement description; it does not affect PASS/FAIL | Natural convection, forced airflow, PCB construction, heatsinking and load conditions are not compared structurally | **`UNKNOWN` until required thermal conditions are structurally compatible with evidence conditions** |
| `confirmed_by_user` | boolean | Process gate, not a product capability | `evaluate_candidate` precondition | None | None | Screening is rejected unless requirements are confirmed | Must remain separate from engineering qualification | Gate failure, not rule PASS/FAIL |

## 3. Current rule-to-field consumption

| Rule / gate | Requirement fields actually consumed |
|---|---|
| RequirementCard relationship validation | `vin_min_v`, `vin_nominal_v`, `vin_max_v`, `iout_continuous_a`, `iout_peak_a`, surge fields |
| Screening confirmation gate | `confirmed_by_user` |
| `vin.range` | `vin_min_v`, `vin_max_v` |
| `vout.range` | `vout_target_v`, `vin_min_v` |
| `iout.continuous` | `iout_continuous_a` |
| `iout.peak` | `iout_peak_a`, `peak_duration_ms` |
| `surge.input` | `surge_knowledge`, `surge_voltage_v`, `surge_duration_ms` |
| `thermal.ambient` | `ambient_max_c`, `thermal_conditions` |
| **No hard rule** | **`vout_tolerance_percent`** |

Passing a field into a function is not by itself proof that the field affects
qualification. In particular, `thermal_conditions` is currently rendered into
text but does not participate in structural compatibility checking.

## 4. S03 gaps to close

### G03-1: Output tolerance

Add a dedicated rule entry point for `vout_tolerance_percent`.

First-version safety behavior:

- missing structured product accuracy capability -> UNKNOWN;
- missing decisive reviewed evidence -> UNKNOWN;
- output-voltage range evidence alone cannot satisfy the rule;
- feedback-reference accuracy alone cannot be treated as total output accuracy;
- if total error is later calculated, every error source, worst-case combination
  rule, operating condition and evidence binding must be explicit.

The new rule must be added to `DEFAULT_REQUIRED_RULE_IDS` at the same time that
screening begins emitting it.

### G03-2: Thermal applicability

`thermal_conditions` must no longer be decorative text in a rule that can PASS.

A future structural representation must distinguish applicable conditions such
as:

- natural convection versus forced airflow;
- PCB construction / copper area;
- heatsinking;
- load or power dissipation conditions;
- other source-stated thermal assumptions.

An ambient-temperature number may PASS only when the decisive evidence is
applicable to the requested thermal conditions. Missing applicability data must
produce UNKNOWN.

### G03-3: Peak-current applicability

The explicit peak-current path already requires current and duration.

The continuous-current fallback is not sufficient by rating magnitude alone.
Before it can grant PASS, the continuous rating must be applicable to the
requested electrical and thermal operating conditions. If those applicability
conditions are absent or incompatible, the result must be UNKNOWN.

### G03-4: Surge boundary

The current conservative boundary is retained:

- `PRESENT` surge -> UNKNOWN until a qualified transient model exists;
- `UNKNOWN` surge -> UNKNOWN;
- Absolute Maximum VIN is not a normal transient operating capability;
- `NONE_EXPECTED` is distinct from unknown.

S03 must not weaken this behavior.

## 5. Coverage invariant for future requirement fields

Every requirement field that can affect formal engineering qualification must
have an explicit disposition:

1. consumed by one or more hard rules;
2. consumed as a structural applicability condition of a hard rule; or
3. explicitly classified as context / process-only and documented as such.

A field may not be required for user confirmation and then silently disappear
from formal screening.

Future tests must fail when a newly collected hard requirement has no rule or
applicability consumer.

## 6. S03 implementation order

1. Freeze this baseline matrix.
2. Add the output-tolerance rule with UNKNOWN-first behavior.
3. Add that rule to screening and `DEFAULT_REQUIRED_RULE_IDS`.
4. Add a coverage test for collected hard requirements.
5. Introduce structured thermal applicability and prevent numeric-only PASS.
6. Tighten continuous-current fallback used by `iout.peak`.
7. Re-run formal-classification regression tests, including:
   - requested +/-2 percent with no accuracy evidence -> not FORMAL;
   - sufficient ambient temperature but unresolved natural-convection
     applicability -> not FORMAL;
   - Absolute Maximum VIN alone -> never surge PASS.

No existing published product or evidence review state is changed by this
matrix.
