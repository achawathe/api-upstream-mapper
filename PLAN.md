# API Mapper — Requirements & Plan

Status: **built** (all nine steps). See README.md for usage, design and measured accuracy.

Channel value mapping: enum conversion now distinguishes source-field lineage from
value translation into the channel's allowed set. Specification enums take priority;
explicit documented lists and independent API value meanings supplement definitions. Reviewed tables
support normalization and allowed fallbacks, and are checked on save and replay.
See docs/channel-value-mapping.md for scope and example inputs.

Update (2026-10-19, documentation and editor): optional per-API documentation now
feeds cited local matching context; General applications is a selectable vocabulary.
A Scratch-inspired Blocks view connects a source through editable conversion steps
to an output field, with categories, explicit saves and example previews. See
docs/documentation-and-editor.md for scope and validation limits. The latest 99-case
public-contract check gives 40 correct origins, zero wrong suggestions, eight missed
origins and 51 correct abstentions in both rules and local MiniLM mode.

Update (2026-10-19): candidate comparisons now quote recorded purpose evidence from
schema descriptions and attached examples. A bounded YAML vocabulary supports discovery
and conflict checks independently of optional embeddings. New context-based discoveries
remain review suggestions with their original scores. The detail pane, JSON and Excel
explain selected and competing candidates; no generated rationale is treated as proof.
The focused six-field FDX/Plaid diagnosis improves from 2/6 to 6/6 correct decisions
in both rules and local MiniLM mode. It identifies dropped list descriptions, skipped
single-record ownership checks, missing definition support and duplicate API uploads.
See docs/local-nlp-diagnosis.md; these development cases do not establish general parity.
An optional upstream model-file attachment now resolves missing local `$ref` files after
the initial spec upload, refreshes warnings and preserves existing response examples.

Update (2026-10-16): the user's local NLP feature request supersedes the historical
rules-only restrictions in F4 and N1 below. Rules remain the default; optional offline
sentence embeddings supplement candidate discovery and scoring. All type vetoes and
penalties remain, and candidates discovered only through NLP require human review.
See README.md for configuration and reproducibility limits. The original requirements
below are retained as design history.

## 1. What the tool is

A deterministic (no AI / no ML) tool that takes:

- **one upstream spec** — the requirement (e.g. FDX). Swagger 2.0 / OpenAPI 3.x, YAML or JSON, either a full spec or a schema-only fragment
- **N downstream specs** — the APIs we actually call (typically 3–7, must scale to 50+)
- **optional sample JSON payloads** — for downstreams that have no spec, or to sharpen matching with real values

…and produces a field-level mapping: for every upstream field, *which downstream API, which endpoint, which field path, what transform*, with a confidence score and the evidence behind it. Results are browsable and editable in a GUI and exported to Excel.

## 2. Requirements (consolidated from both notes)

### Functional

| # | Requirement |
|---|---|
| F1 | Load Swagger 2.0 and OpenAPI 3.0/3.1, YAML or JSON; resolve `$ref` (local + external files), `allOf` / `oneOf` / `anyOf`, discriminators |
| F2 | Accept sample JSON responses; infer a schema from them (merge multiple samples, detect nullable / optional / arrays) |
| F3 | Auto-map downstream fields → upstream fields across any number of downstream APIs, handling naming drift (`accountId` ↔ `account.id` ↔ `acct_no`) |
| F4 | "Semantic" + fuzzy matching using **logic only**: tokenization, abbreviation expansion, curated finance synonym lexicon, string similarity, type/format compatibility, enum overlap, sample-value patterns, structural/API context |
| F5 | Resolve ambiguity (`creditAccount.id` vs `debitAccount.id` vs `account.id`) using context: parent object, endpoint path, API title/tags, and implied API scope (a "Credit Card API" makes its bare `id` a credit account id) |
| F6 | Support non-1:1 mappings: one upstream field from several downstreams conditionally (e.g. by account type), many→one (`firstName` + `lastName` → `name`), and multiple calls to the same downstream (list accounts → per-account transactions) |
| F7 | Deterministic transforms: type casts, cents ↔ decimal, date/epoch formats, enum value maps (`CHK` → `CHECKING`), sign conventions (debit/credit indicator + absolute amount → signed amount) |
| F8 | Map downstream error responses (HTTP status + body codes/messages) to the upstream error model |
| F9 | Show, per upstream endpoint, which downstream APIs/endpoints it needs and in what order (the "call plan") |
| F10 | Flag gaps: required upstream fields with no source, type conflicts, enum values with no match, fields claimed by conflicting sources |
| F11 | GUI: upload inputs, watch the pipeline run live (each stage + counts + log), browse/filter mappings, see score breakdown, optionally override (accept / reject / pick another candidate / edit transform), re-run keeping overrides |
| F12 | Excel export + in-GUI mapping report |
| F13 | Validate mappings end-to-end against mock downstreams built from specs/samples (see open question Q1) |

### Non-functional

| # | Requirement |
|---|---|
| N1 | **No AI, ever.** Same inputs → same outputs, byte-for-byte. Stable tie-breaking |
| N2 | **Accuracy is the priority.** Every auto-decision is explainable; uncertain matches go to "needs review", never silently accepted |
| N3 | Performance: 50 downstream specs mapped in seconds, not minutes; concurrent downstream calls in validation mode |
| N4 | Clean architecture: modular packages, models separated, small single-purpose modules |
| N5 | Readable code that explains itself; comments only at module top or where a requirement is non-obvious |
| N6 | Robust to malformed / partial specs — clear error, never crash the run |

## 3. Key decisions (recommended)

| Decision | Choice | Why |
|---|---|---|
| Language | **Python 3.12** | You preferred Python/JS. Python has the best libraries for this exact job (YAML/OpenAPI, Excel, fuzzy matching) and reads cleanly |
| Fuzzy matching | `rapidfuzz` | Deterministic, C-backed, vectorized (`cdist`) — handles 10M+ comparisons fast |
| "Semantic" matching | Curated lexicon in YAML (synonyms, abbreviations, domain qualifiers) | Gives semantic behaviour with zero AI; editable by you in the GUI |
| Excel | `openpyxl` | Formatting, multiple sheets, filters, conditional colors |
| Backend | `FastAPI` + Server-Sent Events | Live progress streaming to the GUI |
| GUI | Static HTML + vanilla JS (no build step) | Nothing to compile, easy to read; Streamlit is the simpler alternative but can't do the live-process view and workbench well |
| Models | Python `dataclasses` (frozen where possible) | Plain, typed, no framework lock-in |
| Tests | `pytest` | Unit + golden + stress suites |

## 4. How matching works (all logic)

Pipeline stages — each one emits progress events the GUI shows live:

1. **Load** — parse every spec / sample; record parse errors per file
2. **Resolve** — dereference `$ref`, flatten `allOf`, expand `oneOf` branches with discriminator labels; detect cycles
3. **Flatten** — turn every schema into field nodes: `path`, `type`, `format`, `enum`, `required`, `nullable`, `example`, parent chain, endpoint, API
4. **Context tagging** — derive qualifiers per field from parent names, path, schema name, API title/tags (`credit`, `deposit`, `loan`, `customer`, `transaction`…)
5. **Normalize names** — split camel/snake/dot/kebab → tokens; expand abbreviations (`acct`→`account`, `amt`→`amount`, `bal`→`balance`, `dr`/`cr`); singularize; map synonyms to canonical concepts
6. **Candidate generation (blocking)** — inverted index on canonical tokens + type compatibility, so we don't score every pair blindly
7. **Score** — weighted sum of independent signals, each stored as evidence:
   - token / concept overlap
   - string similarity (Jaro-Winkler, token-set ratio)
   - type + format compatibility
   - enum overlap
   - sample value pattern agreement (ISO dates, currency codes, routing numbers, IBAN)
   - context qualifier agreement (penalize `debit` vs `credit` mismatch hard)
   - structural agreement (same parent concept, same array depth)
8. **Assign** — choose best candidate per upstream field; detect conflicts and near-ties (top-2 within margin → "needs review")
9. **Transforms** — infer required conversion from type/format/enum/unit differences
10. **Classify** — `auto-accepted` (score ≥ high threshold, no conflict), `needs review`, `unmapped`
11. **Call plan** — group mapped fields by downstream endpoint; order calls by ID dependencies (path params sourced from other responses)
12. **Report** — GUI + Excel

## 5. Architecture

```
api-mapper/
  pyproject.toml
  src/api_mapper/
    models/        FieldNode, ApiSpec, Endpoint, Candidate, Evidence, Mapping, Transform, ErrorMapping, CallPlan
    loaders/       openapi_loader, ref_resolver, sample_inference
    normalize/     tokenizer, lexicon, context_tagger, flattener
    matching/      candidates, signals/, scorer, assigner
    transforms/    type_casts, units, dates, enums
    errors/        error_mapper
    planning/      call_planner
    validation/    mock_downstream, executor (async, concurrent)
    pipeline/      orchestrator, progress events
    reporting/     excel_report, json_report
    api/           FastAPI routes + SSE
  web/             index.html, app.js, styles.css
  lexicon/         finance_synonyms.yaml, abbreviations.yaml, qualifiers.yaml
  samples/
    upstream/fdx/
    downstream/<api-name>/  spec + sample payloads
    answer_key.yaml         ground-truth mapping for accuracy tests
  tests/  unit/  golden/  stress/
```

## 6. Test data

**Upstream:** Plaid Core Exchange 6.4 — a public OpenAPI 3.0.3 subset of FDX 6.4 ([plaid/core-exchange](https://github.com/plaid/core-exchange)). It already contains the hard cases: polymorphic accounts (Deposit / Loan / LineOfCredit / Investment / Insurance / Annuity / Commercial) via discriminators, transactions, statements, customers, payment networks, contact info.
Note: its header says use constitutes acceptance of the FDX API License Agreement — fine for internal testing, but your call (Q4).

**Real-world downstream sanity check:** UK Open Banking Read/Write API specs ([OpenBankingUK/read-write-api-specs](https://github.com/OpenBankingUK/read-write-api-specs)) — a real, different naming convention (`OBReadAccount6`, `Data.Account[].AccountId`).

**Fake downstreams (I'll write these)** — deliberately ambiguous, data split across APIs:

| API | Traps it contains |
|---|---|
| Core Banking Accounts | `account.id`, `acct_no`, amounts in cents, nested `balances.current.amount`, `accountType` codes (`CHK`, `SAV`, `CC`) |
| Credit Card API | bare `id` that means credit account id (API scope), `creditLimit`, `stmtBal`, `minPmtDue` |
| Deposit / Debit API | `debitAccount.id`, `availBal`, `ledgerBal` |
| Loans API | `loan_id`, `principal_bal`, interest rate as percent string |
| Customer / Party API | split names (`given`, `surname`), contacts array, `customerId` join key |
| Transactions Ledger | `txnId`, epoch-millis timestamps, `drCrInd` + absolute amount, `counterparty` |
| Routing / payment info | **sample JSON only, no spec** (`routing.aba`, `acctNum`) |
| Transfers API (decoy) | `fromAccountId`, `toAccountId`, `parentAccountId`, `externalAccountId` — similar names, wrong meaning |

Each with its own error format (different status codes, `{code,msg}` vs `{errors:[…]}`).
An **answer key** lists the correct mapping for every upstream field.

## 7. Accuracy & stress testing

- **Golden test:** run the full pipeline on FDX + fake downstreams, compare to the answer key → precision / recall / F1 per field and per endpoint. Proposed bar: **≥ 98% precision on auto-accepted**, **zero wrong auto-accepts on required fields**, everything else lands in "needs review" rather than wrong
- **Mutation stress test:** programmatically generate 50 downstream variants by renaming (case, abbreviation, synonym), re-nesting, splitting fields, adding decoys — measure accuracy and runtime
- **Determinism test:** run twice, diff outputs — must be identical
- **Edge-case unit tests:** circular refs, recursive schemas, arrays of arrays, `additionalProperties` maps, nullable vs required mismatches, duplicate `operationId`s, empty specs, malformed YAML, unicode names, deprecated / readOnly fields, same field from multiple downstreams
- **Performance benchmark:** 50 downstreams × ~500 fields → target under 10 s end-to-end mapping

## 8. Excel output (sheets)

Summary · Field Mapping · Needs Review · Gaps (unmapped, required first) · Conflicts · Transforms & Enum Maps · Call Plan · Error Code Mapping · Run Log
Field Mapping columns: upstream endpoint, upstream path, type, required, downstream API, endpoint, path, type, transform, confidence, status, evidence summary, manual override (Y/N).

## 9. Build order

1. Models + loaders + ref resolver (with tests)
2. Flattener, tokenizer, lexicon, context tagger
3. Fake downstreams + answer key (written *before* the matcher, so accuracy can't be tuned to the data unknowingly)
4. Signals, scorer, assigner → golden accuracy test
5. Transforms, error mapping, call planner
6. Excel report
7. FastAPI + GUI (upload, live run, workbench, report)
8. Validation harness against mock downstreams
9. Stress + performance suite, tune, document

## 10. Decisions log

| Question | Decision |
|---|---|
| Scope of "calling downstreams" | Mapping tool **plus** validation harness calling mock downstreams concurrently (errors, multi-call chains). No production gateway |
| Manual override | Auto-map by default; overrides optional, flagged in report, persisted across re-runs |
| Upstream test spec | Plaid Core Exchange 6.4 (public FDX 6.4 subset) |
| "Semantic" boundary | Lexicon + rules only; no embeddings or any pretrained model |
| "Top-level spec or not" | *Assumed:* upstream may be a full spec or schema-only fragments — both supported |
| Location | *Assumed:* `api-mapper/` in this workspace |

## 11. Outcome vs plan

| Planned | Result |
|---|---|
| ≥ 98% precision on automatic mappings, zero wrong automatic mappings on required fields | 100% on the golden set (189 automatic, 0 wrong), 100% on 8 lexicon-rename seeds, 16 unseen-spelling seeds and the 50-API noise run |
| 50 downstreams in under 10 s | 0.9 s (200 APIs: 3.4 s) |
| Determinism | Tested: two runs serialise byte-for-byte equal |
| Real-world downstream | UK Open Banking Account and Transaction spec (2,898 fields) maps in about 2.5 s |

Added beyond the plan, because testing showed they were needed:
- reading unknown spellings (`blnc`, `entri`) against the lexicon and upstream vocabulary, shown as evidence
- reachability: a source must be callable for the record the upstream request names
- variant routing in the validation harness, using every candidate already fetched
- enum maps inferred from sample values for spec-less APIs
- Python 3.13 venv (3.12+ supported)


## 12. Public-contract validation follow-up (2026-10-16)

The original UK Open Banking result above measured loading/runtime only. The new
`samples/real-contracts` benchmark checks exact origins against a documented 99-label
answer key for UK Open Banking and Plaid. Both updated rules and local MiniLM NLP find
22/48 source-bearing labels. Incorrect automatic origins fell from 5 (rules) / 4 (old
NLP) to zero in this bounded scope; two correct-origin automatic suggestions still
have adapter conditions. Full FDX parity is not established. See the benchmark README
for misses, incorrect review suggestions, provenance and reproducible commands.

Implementation follows N4/N5: scoring evidence, review safeguards and contract grading
are separate small modules, with plain data models and finance vocabulary in YAML.
Local NLP remains optional and cannot promote a rule-level review into an automatic
mapping. The existing rules-only golden set retains all 164 required expected origins
and zero incorrect automatic mappings; six additional origins now require review.


## 13. Request context and meaning follow-up (2026-10-16)

JSON request bodies now survive loading into the endpoint model. Small helpers handle
body extraction, compatible input binding and request construction. Exact account
selectors establish conditional reachability; credentials are never identity evidence.
Every body-dependent origin, including dependent calls, stays under review. Mock
execution sends nested JSON and blocks calls lacking required inputs. Identifier
namespace compatibility and response record selection still need confirmation.

Financial meaning constraints remain declarative in `lexicon/finance.yaml`. They
distinguish transaction events, currency roles/standards, names versus identifiers and
classification systems when explicitly described. They constrain both scoring modes.
A local leading-definition embedding experiment added no correct origins and was not
adopted; model and NLP thresholds remain unchanged.

The same frozen 99-label key now yields 31/48 correct origins in both modes (UK 16/23,
Plaid 15/25), nine misses, 21 wrong review suggestions, and zero wrong automatic origins.
The broader candidate coverage increases wrong reviews from 18 to 21; this is a stated
trade-off, not a claim of parity. Nine origins are automatic, one conditional. The
finance golden key still finds 164/164 expected origins, with 138 required automatic
choices and zero wrong automatic choices. This benchmark informed development; an
independently reviewed unseen provider remains necessary to measure generalization.


## Documentation examples and activity logging (2026-10-19)

Upstream and downstream Swagger/OpenAPI models remain authoritative. Upload bundles
preserve relative reference paths and identify the API entrypoint independently of file
order. JSON success responses from documentation attach to explicit endpoints on either
side, supplement observed-value matching and bounded local NLP context, and retain file
provenance without changing declared fields, types, enums or requiredness.

Local NLP remains optional and review-safe. The public-contract comparison remains
31/48 correct origins and zero wrong automatic origins with the attached examples;
no new accuracy gain is claimed. Small modules handle bundle selection, attachments,
sample context and persistent activity history. The Run screen shows a concise live
status, with detailed logs collapsed by default. Workspace actions and run stages are
recorded locally with bounded retention, excluding payloads and free-form review notes.


## Review fixes (2026-10-20)

Earlier figures in this log (for example 31/48 correct origins) are superseded by the
README's measured-accuracy table.

- A held-out benchmark (Australian CDR banking and common APIs, MIT, pinned in
  `samples/held-out/cdr`) was labelled before its first run. That run scored 66.7%
  precision and 34% recall, for the base rules as much as for later additions. Two general
  defects caused most of it: tags set an API-wide account family ("Direct Debits" made the
  whole banking API a deposit API), and single-record fields could come from endpoints
  about another record (a payee's nickname). Both are fixed. The one remaining wrong
  automatic mapping (FDX `category`, defined as an MCC, from CDR's `type` enum) is fixed by
  a lexicon purpose rule for merchant category codes, with MCC accepted as a `category`
  source in the CDR and Northwind keys. CDR now scores 100% / 98.5% and is no longer
  untouched.
- Enum review now looks across sibling variants: a deposit variant's map leaving out `CC`
  is not a gap when the credit variant accepts it. Free-text sources into a closed list keep
  their automatic source decision with a runtime-validity note. Northwind automatic
  decisions returned from 82% to 87%.
- Evidence signals are a `Signal` enum; an unknown name now raises instead of silently
  disabling a rule. A lexicon flag (`expects_labels`) replaces a `product_label` special
  case in code.
- ruff format and lint rules are configured in `pyproject.toml` and the codebase passes them.
- `tools/nlp_effect.py` measures the local model: it changed 0 and 1 decisions on the two
  benchmarks with no accuracy change, at 6–11 times the runtime.
- The Qwen reranker adapter and its data stay in git so the experiment is portable; the
  Qwen3-4B base model it needs is not included.
