# VoltSpace backend — adversarial review

> **Status: this review was carried out on an earlier revision and every finding has since
> been resolved. The findings below are kept as a record of what was wrong, why, and how
> it is now covered by tests.**
>
> | Finding | Severity | Status | Regression test |
> | --- | --- | --- | --- |
> | F1 `phases` validated then ignored | High | **Fixed** — `phases` is forwarded through `estimate_appliance_loads()`, `estimate_load()` and `find_overload_combinations()` | `test_load_estimator.py::TestLoadEstimate::test_three_phase_*`, `test_api.py::TestLoadEndpoint::test_three_phase_*` |
> | F2 `/simulate` ignored `billing_months` | Medium-High | **Fixed** — passed through to both bills and echoed as `billing_months` | `test_simulation.py::TestOptions::test_billing_months_*`, `test_api.py::TestSimulateEndpoint::test_billing_months_is_forwarded_to_the_bill` |
> | F3 renaming swap split one row into two | Medium | **Fixed** — the pre-swap identity is recorded (`replaced_from`) and rows stay keyed by the original name, with `replaced_by` for the new name | `test_simulation.py::TestRenamingSwap`, `test_api.py::TestSimulateEndpoint::test_renaming_swap_keeps_one_comparison_row` |
> | F4 dedup by rule id dropped a second appliance's advice | Medium | **Fixed** — dedup and saving aggregation key on the appliance identity, not the name; `recommendation_key` / `appliance_key` added | `test_recommendations.py::TestSavingAggregation::test_two_identical_appliances_*`, `test_api.py::TestRecommendationsEndpoint::test_two_identical_appliances_both_get_advice` |
> | F5 Chinese names containing an alias never matched | Medium | **Fixed** — exact and substring aliases are scored together; the longest alias wins | `test_recommendations.py::TestRules::test_chinese_and_decorated_names_resolve_to_the_catalogue` |
> | F6 README example block stale | Low (doc) | **Fixed** — README example regenerated from the generated artifact | `docs/examples/recommendations_student_room.json` |
> | F7 stale test/example counts | Low (doc) | **Fixed** | — |
>
> Post-fix verification: `python -m pytest` → **416 passed**;
> `python tools/probe_errors.py` → 51 probes, no 5xx;
> `python tools/smoke_api.py` → all checks pass.
>
> One further inconsistency was found while regenerating the README examples after the
> fixes above: `per_appliance[].recommendation_count` counted only the per-appliance
> rules and omitted the household-level swap advice, so the summary disagreed with the
> `recommendations` array it describes (2 vs 3 for the air conditioner). It is now
> computed from the final returned list, and `test_recommendations.py` asserts the two
> always reconcile.

Environment used: `python C:\Users\Vince\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe`,
`PYTHONPATH=...\backend\.pylibs`, workdir `backend`.
Baseline at review time: `python -m pytest` → **371 passed**.

No project file was modified by the review. The scratch harnesses it wrote were removed
after the findings were reproduced and fixed.

---

## Findings

### F1 — `/calculate/load` accepts `phases: 3` and then silently ignores it (73% current error)

* `app/calculators/load_estimator.py:174` — `current_amps(power, voltage, power_factor)` is called
  **without `phases`**, so `phases` defaults to 1.
* `app/calculators/load_estimator.py:253-257` — `estimate_load` validates `phases` then never
  forwards it.
* `app/schemas.py:311` + `app/main.py:361` — the API exposes `phases`, passes it, and
  `app/schemas.py:338` echoes it back in the response.

Reproduction:

```python
from fastapi.testclient import TestClient
from app.main import app
c = TestClient(app, raise_app_exceptions=False)
r = c.post("/calculate/load", json={
    "appliances": [{"name": "A", "power_watts": 3000, "hours_per_day": 1, "voltage": 220}],
    "phases": 3, "load_limit_amps": 15}).json()
print(r["phases"], r["estimated_total_current_amps"])
```

Observed: `3 13.6364` (`verdict = near_limit`).
Expected: `3 7.8730` = `3000 / (1.732 * 220)`, `verdict = safe`.
The library helper is correct in isolation (`current_amps(3000, 220, 1.0, phases=3) == 7.8730`), and
`README.md:273-275` documents the 3-phase formula, so the endpoint is wrong, not the helper.
**Severity: High** — the module's whole purpose is a load warning; a 1.73x over-estimate raises
false "near limit / over limit" alarms for any user who selects 3-phase.
**Why tests missed it:** `tests/test_load_estimator.py:42-44` only tests the helper; no test drives
`phases=3` through `estimate_load`/the endpoint.

---

### F2 — `/simulate` silently ignores `billing_months`

* `app/schemas.py:504` — `SimulationRequest(TariffOptions)` therefore advertises `billing_months`
  (`app/schemas.py:130-135`).
* `app/services/simulation.py:113-121` — `simulate()` has **no `billing_months` parameter**.
* `app/main.py:519-527` — the endpoint forwards `billing_period` but never `billing_months`.

Reproduction:

```python
payload = {"appliances": [{"appliance_id": "a1", "name": "AC", "power_watts": 900,
                           "hours_per_day": 9, "days_per_month": 30, "voltage": 220}],
           "changes": [{"appliance_id": "a1", "field": "hours_per_day", "value": 9}],
           "month": 8, "billing_months": 2}
print(c.post("/simulate", json=payload).json()["baseline"]["estimated_bill_twd"])
```

Observed: `502.95` (single-month tiers) and `billing_period: "monthly"` in the response.
Expected: `410.55`, identical to
`POST /calculate/cost {"consumption_kwh": 243, "month": 8, "billing_months": 2}` → `410.55`.
So the same 243 kWh is billed two different ways by two endpoints, silently.
`billing_period: "bi_monthly"` **is** forwarded correctly (verified), so only `billing_months` is dead.
**Severity: Medium-High** — same schema field, two endpoints, two answers; no error is raised.

---

### F3 — A name-changing `replace_with` without `appliance_id` splits one swap into two bogus rows

* `app/services/simulation.py:82-84` — the replacement overwrites `result["name"]`, destroying the
  baseline identity.
* `app/services/simulation.py:343-362` — `_appliance_deltas` pass 1 matches by `appliance_id`; pass 2
  matches by name.

Reproduction (this is also the shape of the OpenAPI example at `app/main.py:498-509`, minus the id):

```python
payload = {"appliances": [{"name": "AC", "power_watts": 1400, "hours_per_day": 8, "voltage": 220}],
           "changes": [{"name": "AC", "field": "replace_with",
                        "replacement": {"name": "NewAC", "power_watts": 700}}]}
print(c.post("/simulate", json=payload).json()["comparison_table"])
```

Observed:
```json
[{"appliance":"AC","baseline_kwh":336.0,"modified_kwh":0.0,"saved_kwh":336.0,"percent_change":-100.0},
 {"appliance":"NewAC","baseline_kwh":0.0,"modified_kwh":168.0,"saved_kwh":-168.0,"percent_change":null}]
```
Expected (what the identical request *with* `appliance_id` returns):
`[{"appliance":"AC","baseline_kwh":336.0,"modified_kwh":168.0,"saved_kwh":168.0,"percent_change":-50.0}]`
The totals in `delta` are correct; the **per-appliance table is wrong** and would render as
"AC removed (‑100%)" + "NewAC added". Also note `applied_changes[0].appliance` reports the *new* name
`NewAC` while `comparison_table[0].appliance` reports the *old* name `AC`.
**Severity: Medium** — requires omitting `appliance_id`, which the schema permits and
`README.md:485` explicitly allows ("指定對象用 `appliance_id` 或 `name`").

---

### F4 — Recommendation dedup by `id` drops legitimate advice for a second appliance

* `app/services/recommendations.py:357-372` — catalogue rules are keyed by `rule["id"]` only, not by
  appliance.
* `app/services/recommendations.py:465-471` — dedup keeps the first occurrence per `id`.

Reproduction:

```python
payload = {"appliances": [
    {"appliance_id": "a1", "name": "冷氣機", "power_watts": 900, "hours_per_day": 9, "voltage": 220},
    {"appliance_id": "a2", "name": "冷氣機", "power_watts": 900, "hours_per_day": 12, "voltage": 220}],
    "month": 8}
```

Observed: only one `ac_hours_high`, carrying `a1`'s context
(`assumption_zh: "假設每日可減少 2.0 小時使用（原 12.0 小時）"` — i.e. a2's numbers, a1's entry);
the 12 h/day appliance never appears in `recommendations`.
Expected: one entry per appliance (different hours ⇒ different saving: 48.6 vs 54.0 kWh).
The same collapse happens to `top_consumer_*`? No — that key already includes the normalised name,
so only catalogue/`rule_id` rules and `swap_*` are affected. (Dedup itself is intentional —
`tests/test_recommendations.py:309` asserts it — the defect is that the key is too coarse.)
**Severity: Medium**

---

### F5 — `_match_reference` returns early, so natural Chinese names never reach the fuzzy pass

* `app/services/recommendations.py:65-80` — the exact/alias loop returns on first hit, and the
  substring fallback (`:76-79`) only runs when **no** candidate matched at all.

Measured (`_match_reference({"name": ...})`):

| input | result |
| --- | --- |
| `冰箱` | `refrigerator` |
| `電冰箱` | `None` |
| `小冰箱` | `None` |
| `電視` | `tv` |
| `電視機` | `None` |
| `照明` | `lighting` |
| `房間照明` | `None` |

These are 3-character inputs, so the `len(key) >= 3` guard is not the blocker — the input *contains*
the catalogue key (e.g. `冰箱` ⊂ `電冰箱`), which is exactly when the fallback is skipped.

Effect through the API: `{"name": "電冰箱", ...}` yields `matched_catalog_key: null` and falls to
generic advice (`generic_long_hours_*`), losing `fridge_always_on` and `swap_refrigerator`:

```
冰箱    matched=refrigerator  count=3  ['top_consumer_0_冰箱', 'swap_refrigerator', 'fridge_always_on']
電冰箱   matched=None          count=2  ['top_consumer_0_電冰箱', 'generic_long_hours_電冰箱']
小冰箱   matched=None          count=2  ['top_consumer_0_小冰箱', 'generic_long_hours_小冰箱']
```

**Severity: Medium** — the target users are Chinese-speaking and will type these variants.

---

### F6 — README's own `/recommendations` example is stale and cannot be reproduced

* `README.md:350` claims `"recommendation_count": 7` ✓ but `README.md:383` claims
  `"recommendation_count": 3` for 冷氣機.
* `README.md:368` claims `"假設每日可減少 2.0 小時使用（原 9.0 小時）"`.
* `README.md:367` claims `"estimated_annual_saving_twd": 1386.24`.

Actual (and already correct in the generated artifact
`docs/examples/recommendations_student_room.json:220,82,64`): `recommendation_count: 2`,
`1.8 小時`, `1386.2`.
`1.8` is the correct value: `min(cap_hours=2.0, 9 * reduction_ratio=0.2, 9) = 1.8`.
**Severity: Low** — documentation-only, but this is the page Member A integrates from, and
`README.md:44` advertises the examples as "由程式產生，不會過時".

---

### F7 — Stale counts in README

* `README.md:34`, `README.md:88`, `README.md:546` say **364** tests; actual is **371**.
* `README.md:551-556` per-file counts (53/77/46/48/49/91) do not match parametrised collection
  (315 `def test_` functions, 371 collected).
* `README.md:44` says 13 example files; `docs/examples/` contains 14 files (13 examples + `index.json`).
**Severity: Low**

---

## Suspicious things I checked that are FINE

* **`_calculate_tiered` accumulation** — exact match against an independent reimplementation at
  0 / 0.5 / 1 / 119 / 120 / 121 / 330 / 331 / 500 / 700 / 1000 / 1001 / 1500 / 3000 kWh for both
  seasons. The Taipower worked example (Aug 800 kWh) gives `2977.10`, matching
  `README.md:518` and Taipower's printed `2,977` to the documented rounding tolerance.
  `range_from/range_to` are contiguous and `sum(lines[].amount) == total_amount` for all probes.
* **Proration** — `bi_monthly` × 1040 kWh == 2 × `monthly` 520 kWh == `2891.8`; `billing_months`
  correctly overrides `billing_period`; tier ceilings scale by billed months.
* **Effective rate** — `total_amount / consumption_kwh`, exact for 100/520/1234 kWh; `0.0` for
  0 kWh (no ZeroDivisionError).
* **`find_overload_combinations` loop/break** — the `break` after the first size that produced
  matches is correct: it reports only the smallest offending size, capped at 10, and `smallest_flagged`
  is always set before the break. Does not blow up: n=8/12/16/20 with `max_combination_size=6`
  (up to 60k combinations) all return in <0.01 s. `min()` against `len(loads)` is safe.
* **`_estimate_rule_saving` cap path** — `min(cap_hours, hours*ratio, hours)` is correct and never
  negative; hours 1→0.2 h, 9→1.8 h, 12→2.0 h (cap binds), 24→2.0 h.
* **`reduction_ratio: 0` rules** — correctly routed to the `advice_only` branch (hair dryer), with
  `confidence="high"`, zero claimed saving.
* **NaN / Infinity** — my first harness run suggested a NaN 500; that was a harness artefact. In fact
  `Field(le=100000)` rejects NaN (`nan <= 100000` is False) with 422, and
  `consumption._require_number` independently rejects non-finite values with
  `ValidationError("power_watts must be a finite number")`. No 5xx reachable this way.
* **Malformed input handling** — malformed JSON, empty body, `null`, a JSON string, a JSON array and
  form-encoded bodies all return a well-formed 422 from the `RequestValidationError` handler
  (`app/main.py:99-122`), including the `details` list (no Pydantic serialisation warning).
* **Exception-handler shadowing** — `ValidationError`, `TariffError`, `SimulationError`, `LoadError`
  all subclass `ValueError`, but FastAPI resolves handlers by exact class, so
  `@app.exception_handler(ValueError)` (`app/main.py:152`) does **not** swallow them. Verified: a
  bad `power_watts` returns `code: power_not_positive` (422) and an unknown `appliance_id` returns
  `code: appliance_not_found` (400), not `invalid_value`.
* **`voltage: None` / omitted voltage** — works on all five endpoints. `validate_appliance` guards
  with `isinstance` before `float()`, and `estimate_appliance_loads` uses `item.get("voltage") or
  default`. (A `float(None)` TypeError in `consumption._as_appliance` is unreachable because
  `validate_appliance` runs first.) I initially flagged this as a 500 path — it is not.
* **Non-mutation guarantee** — `simulate()` leaves both the input list and a list of `ApplianceIn`
  models byte-identical after a `replace_with`. `README.md:485-486` holds.
* **`effective_rate_per_kwh`, `blended_rate_per_kwh`, `saved_percent_*`** — all divisions guarded;
  no ZeroDivisionError reachable.
* **Cross-endpoint consistency** — `/calculate/consumption` total == `/calculate/cost`
  (`computed_total_monthly_kwh` and `consumption_kwh`) == `/simulate` baseline ==
  `/recommendations` `total_monthly_kwh` (381.6 kWh on the README example).
* **Season handling** — Jun/Sep → summer, May/Oct → non_summer, `season` correctly overrides
  `month`; unknown `plan_id` is rejected by the `Literal` (422).
* **`peak_share`** — correctly ignored by non-TOU plans (verified identical totals for 0.0 and 1.0)
  and applied by the TOU plan (400 kWh, share 0.5 → 1458.0).
* **"No rate hard-coded in code"** — no rate literal (`1.68`, `2.45`, `8.46`, `6.63`, `5.16`, …)
  appears in `app/**/*.py`, `tools/*.py` or `tests/*.py`; `flat`/`tou`/`tiered` all read
  `tariffs.json`. Claim holds.
* **Catalogue rules** — every `when` condition used in `appliances.json` is supported by
  `_rule_matches` (no silently dead rules). All 12 catalogue entries return HTTP 200.
* **Catalogue index collisions** — the 8 "collisions" are benign alias duplicates (`key ==
  name_en.lower()` for single-word names); no two *different* entries collide.
* **`annual_seasonal_estimate` / `compare_plans` / `what_if_reduction`** — all consistent
  (annual = 4×summer + 8×non_summer; cheapest plan for 400 kWh is correctly the tiered plan).
* **`power_factor`** — accepted by the library but not by `ApplianceIn` (`extra="forbid"` → 422).
  That is a deliberate cost, not a crash; `ApplianceLoadOut.power_factor` is always 1.0. Worth a
  doc note, not a defect.
* **`CostRequest.consumption_kwh` is required even with `appliances`** (the `_need_a_source...`
  validator at `app/schemas.py:230-236` can never fire). It is self-consistent and the README
  example works around it with `"consumption_kwh": 0` (`README.md:213-216`), so this is a UX wart
  rather than a bug — but making it `float | None = None` would match the docstring "忽略
  consumption_kwh".

---

## Suggested fix order

1. **F1** — pass `phases` through `estimate_appliance_loads` → `current_amps` (one-line signature
   change plus a test that drives `phases=3` through `estimate_load`/the endpoint).
2. **F2** — add `billing_months` to `simulate()`/the endpoint, or remove it from
   `SimulationRequest` and return 422 when supplied.
3. **F3** — preserve the baseline name/id when applying `replace_with` (e.g. record
   `replaced_from`) so `_appliance_deltas` can pair the two records.
4. **F4** — key recommendations by `(appliance identifier, rule_id)`.
5. **F5** — run the substring fallback even when an exact match was found, preferring the longest
   key match.
6. **F6/F7** — regenerate the README example block from `docs/examples/recommendations_student_room.json`
   and update the counts (364 → 371, 13 → 14).
