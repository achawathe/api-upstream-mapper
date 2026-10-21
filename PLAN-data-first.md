# Plan: data-first matching and mapping by endpoint

Status: approved 20 October 2026, decisions recorded at the end. Building Workstream A first.

## Goals

1. **Map by meaning, not spelling.** Fields named wildly differently should still map when the
   response data and the documentation agree. Example: a "Weather Snapshot Service" whose
   sample JSON holds the temperature at `snapshot.weather.city.toronto` should beat a
   `station.tempSensorId` or a `cpu.temp` that only shares the word "temp". Likewise a
   downstream `entitlements` should be caught for an upstream `inheritance` when their
   definitions or data agree, although the names share nothing.
2. **Map only what is needed.** Pick the upstream endpoints to map (say three of forty); the app
   maps only those, and the results are grouped by endpoint and object in the GUI.

Hard rules stay: no wrong automatic mapping on any benchmark; uncertain matches go to review.
Review suggestions may be wrong up to 5–10% of the time. Sample JSON is evidence, never proof:
a sample can be partial or unrepresentative, so values support or contradict a match but never
make one on their own.

## What the measurements showed (20 October)

- Sample inference treats every JSON key as a field name. In the weather case the cities
  became five fields (`...city.toronto`, `...city.vancouver`, ...), the temperatures were never
  candidates, and the closest candidates for `temperature` were `station.tempSensorId` (0.26)
  and `cpu.temp` (0.24).
- MiniLM changed 0 decisions on Northwind and four renamed copies, documented or not, at
  thresholds from 0.80 down to 0.50. On CDR, lowering the threshold only added wrong review
  suggestions (59 to 78) with no recall gain.
- Its review fallback requires both fields to have descriptions, so it cannot act on
  undocumented fields, which is where it was meant to help.
- MiniLM scores the correct source about the same as the best wrong one (CDR medians 0.611 and
  0.612). Blending it into the rules' top five never improved the choice.
- Names alone mislead the model; definitions fix it. For `inheritance`, MiniLM ranked
  `inheritedFrom` first (0.668) and `entitlements` at 0.379. With one-line definitions on both,
  `entitlements` ranked first (0.723) and `inheritedFrom` fell to 0.469. Ranking candidates
  against each other works where a fixed 0.80 bar never fires.
- The recall gap is mostly upstream of scoring: on CDR, 11 targets never had the right source in
  the rules' top five.

## Workstream A: map by endpoint

- **Scope setting.** A list of upstream endpoint keys (`GET /accounts/{accountId}`); empty means
  all. Set in the GUI, sent with each run, accepted by the CLI as a repeatable
  `--endpoint "GET /accounts"`.
- **Pipeline.** Targets outside the scope are dropped before profiling and scoring, so a narrow
  run is also a faster run. Downstream sources are not filtered: any downstream can still feed a
  selected endpoint. Call plans cover only the selected endpoints.
- **Overrides and grading.** Overrides for out-of-scope fields are kept and reported as
  inactive, never deleted. Answer-key grading counts only in-scope targets.
- **Reports.** Excel and JSON reports state the scope and include only in-scope fields.
- **GUI, inputs.** An endpoint checklist for the upstream API: search, select all or none, and
  the number of fields per endpoint, from the existing `/api/files/{id}/endpoints` route.
- **GUI, results.** Mappings grouped by endpoint, then object (see decision 1), as collapsible
  sections with per-group counts of automatic, review and unmapped. The current filters keep
  working inside the groups.
- **Tests.** Scope filtering in the pipeline, the API, overrides kept but inactive, grading by
  scope, and a GUI check in the browser preview.

## Workstream B: data and documentation first

Deterministic first; each step lands with its benchmark result.

1. **Value keys in sample JSON.** When sibling keys vary between samples, or look like values
   (city names, dates, IDs, codes, numbers) and all hold the same value shape, read them as a map:
   `snapshot.weather.city{key}`. The key becomes a field of its own (`city`), and a value inside
   the map can be bound to an upstream input with a selection condition (entry where key equals
   `{city}`). Declared `additionalProperties` maps already work this way; inferred ones do not.
2. **Context gives meaning.** A field is judged by its operation ("Weather Snapshot Service",
   `GET /weather/snapshot`), its parent path (`snapshot.weather.city`) and its leaf together.
   A leaf that is a value or an unknown token takes its meaning from its parents.
3. **Values as checks.** From samples and examples: type, format, range, units, sign and
   cardinality. A clear contradiction rules a candidate out (`"TS-104"` cannot be a temperature
   in Celsius); agreement supports it. Values never make a match alone.
4. **Documentation outranks names.** Matching definitions already take precedence over name
   similarity for review. Extend that to definitions attached from separate documents and to
   undocumented sources whose parents are documented.
5. **NLP for narrow questions.** Use the local model where general language knowledge is
   reliable and the answer can be checked: is this key a value or a field name ("toronto" is a
   city), does "temp" mean temperature or temporary here, which expansion fits an unknown
   abbreviation. Answers become explainable evidence; proposed lexicon entries wait for a person.
   Allow NLP retrieval for undocumented fields, ranked against the other candidates rather
   than against a fixed threshold, and embed definitions and parent context, not bare names. A MiniLM fine-tuned on labelled field pairs
   (still about 90 MB, so plain git) is kept only if, on CDR, the correct source beats the best
   wrong one far more often than today's 53%.
6. **Learning from review.** Accepted overrides become project-specific lexicon entries, so the
   next API with the same naming maps without help.

## Benchmarks

- **New: sample-only APIs with value keys and decoys**, starting with the weather case, answer key
  written before the first run.
- **New: name-disjoint synonyms**, such as `inheritance` and `entitlements`, with and without
  definitions, plus spelling decoys like `inheritedFrom`.
- CDR with descriptions removed, and four renamed Northwind copies with and without descriptions.
- The existing Northwind, CDR, UK/Plaid and stress sets must not regress.

## Progress

- **A, map by endpoint:** done (commit `2b4aeab`).
- **B1, value keys:** done. Sample inference reads an object as a map when its keys change
  between samples (most of them, so optional fields do not count) or all look like values
  (IDs, codes, dates, numbers), over same-shaped entries. Maps flatten to `<map>.{key}` and
  `<map>.@key`; names come from the map, records come from the keys, and map fields always go
  to review with the entry to choose. The call plan binds the key to a request input that
  names the same thing (`snapshot.weather.city` ← `{city}`) or lists it as unresolved.
  Value-key benchmark: recall 25% to 62.5%, no wrong automatic mapping, decoys never chosen.
  Northwind, CDR and UK/Plaid unchanged. Still missed: `temperature` (needs B2 and B3), and
  `observedAt` ← `takenAt`, `asOf` ← `date`.
- **B3, value checks:** done. `value_kinds` reads the kind of data a source holds from its
  samples (date, timestamp, currency code, UUID, email, URL, number, text) and the kind a
  target needs from its format, type and definition ("ISO 4217 currency code"). A sample that
  contradicts the target vetoes the candidate (`"TS-104"` cannot be a temperature); agreement
  on a specific kind adds weighted support and brings a source in as a candidate whatever its
  name, but never makes a match on its own. Fields beside a keyed map are reachable in the same
  call, and the call plan binds a map key by value kind (`rates` <- `{currency}`, because the
  keys are currency codes and the echoed `currency` field is one). Value-key benchmark recall
  62.5% to 87.5%, no wrong mapping; Northwind automatic decisions 87.2% to 89.6%, precision
  still 100%; CDR and UK/Plaid unchanged. Units and ranges were left out: they need domain
  priors that would be fitted to this benchmark's decoys. Still missed: `temperature`, whose
  source is named only by its parents (`snapshot.weather.city`), which is B2.
- **B2, context:** done, in two parts chosen from what the renamed sets actually missed.
  (1) Most misses were fields whose own name matched but whose array was renamed past
  recognition (`addrsssPstl[]` for `addresses[]`), which halved their score. A guessed or
  abbreviated array name now agrees through any of its words; a clearly spelled one keeps the
  head-noun rule (`assetTransferNetworks[]` still does not match `transfers[]`). (2) A value
  named only by its keys (`snapshot.weather.city.{key}` when the request has `{city}`) is
  suggested for review when both sides share a context word (`weather`) and it is the only
  field of a native fitting type on both sides; never automatic. Hard-renamed Northwind (16
  seeds) 73-96% to 79-98% recall, mean 92.5%, no wrong automatic mapping; value-key benchmark
  100% recall. Northwind, CDR and UK/Plaid unchanged. Not addressed: renames that reverse
  word order and add filler words to a clearly spelled array name, and leaf spellings the
  resolver cannot read (`NmNick`, `stts`); CDR without descriptions keeps one wrong automatic
  mapping that predates this work.
- **Undocumented CDR:** that wrong automatic mapping was FDX `category` again: without its
  description, `merchantCategoryCode` lost its MCC purpose and `type` won on name similarity.
  Purpose rules can now opt in to reading field names (`match_names`) when a name alone is
  unambiguous; only the merchant-category-code rule does. CDR without descriptions: 0 wrong
  automatic mappings, recall 94.0%; a golden test now runs it.

## Order

1. Workstream A, independent of B and small.
2. B1 with the weather benchmark.
3. B3, then B2.
4. B5 measured on CDR undocumented and renamed sets; keep only what improves them.
5. B4 and B6.

## Decisions (20 October)

1. Results group by endpoint, then variant, then parent object
   (`GET /accounts/{accountId}` > `DepositAccount` > `currency`).
2. The endpoint selection is saved with the workspace and kept across runs and restarts; the
   CLI takes it as a flag.
3. When a value-key map has no matching upstream input, the app may suggest a fixed key
   (`city{toronto}`) for review, with a note; never automatically.
4. Workstream A first, then B1 with the weather benchmark.

## Continuation checkpoint (Codex, 20 October)

Objective: verify Claude's completed A/B1/B3/B2 and undocumented-CDR work, repair
reproducible correctness defects, and make small benchmark-backed commits on
`review-fixes`. The user subsequently authorized pushing and getting the completed
work into `main`. The checkout started clean at `c281596`.

Scope: call planning and recent sample/context matching changes. B5/B4/B6 remain
open; no new model training or learned vocabulary is included in this repair pass.

Progress:
- [x] Recover the latest Claude conversation, commits, approved decisions and plan.
- [x] Reproduce and fix `customerId <- accountId` in the account-balances call plan;
  preserve valid direct bindings, dependency calls and fan-out.
- [ ] Check recent map/context paths for bypassed matching safeguards and malformed
  sample failures; add focused regression coverage for confirmed defects.
- [ ] Run the full suite, lint, and golden accuracy benchmarks; inspect the diff and
  commit fixes in small increments, push, and merge into `main` after validation.

Evidence: `_EndpointPlanner._best_supply` accepts partial overlap >= 0.4, so
unrelated resource identifiers can bind through their common identifier token.
`suggest_from_context` checks type fit before scoring, then assigns its candidate
without checking `vetoed_by` or the existing review safeguards. Both need direct
reproduction before a fix. Baseline: 354 tests passed (40.12 seconds); one existing
Starlette/httpx deprecation warning. The account-balances binding is reproduced.
Sample inference also raises `ZeroDivisionError` on an object with three empty
object values (`_same_shape` divides by an empty union).

Completed: path inputs now require exact concept agreement, after abbreviation,
synonym and resource-context normalization. Unknown customer IDs stay unresolved;
valid aliases, dependency calls and fan-out remain covered. Three negative cases
failed before the fix; all 46 focused planner, body, execution and value-key tests
pass afterward, as does focused lint.

Completed: sample map inference now treats empty object shapes as insufficient
evidence rather than dividing by zero. Three regressions cover ordinary empty
objects, nullable empty objects, and value-like keys with empty values.

Next action: repair the context-review bypass (reproduced for an origin veto and
an unselected outer array), then exercise map execution end to end.

Completed: context-only suggestions now respect candidate vetoes and the existing
`can_review` guards for origin, record, array, enum and other conflicts. Both new
regressions failed before the fix. All 41 focused context, origin, review-guard and
value-key tests pass, including the original temperature suggestion.

Next action: verify map bindings actually select the requested entry during
mock validation; the current extractor only understands named fields and arrays.

Additional confirmed defect: `/api/validate/options` crashes after an endpoint-scoped
run because it looks for plans for excluded endpoints. The existing API test now
checks that validation lists exactly the mapped endpoints. The route skips excluded
plans; complete validation execution coverage is being expanded for keyed maps.

Completed: map selectors now reach response assembly, variant checks and chained
source extraction. Missing selectors and absent keys report issues. Nested maps
schedule every required selection; map values containing arrays retain their named
path and array shape. Selections remain local to the execution and are not sent as
downstream request parameters. The 52 focused tests pass (map extraction/execution,
ordinary validation, flattening, planning and value-key golden checks); focused lint
is clean. Optional benchmark fields that the matcher abstains on remain unmapped.

Next action: check caller-context name collisions for unresolved identifiers, then
run full verification and integrate the small commits into the remote branches.
