# API Mapper

Maps the fields of downstream APIs onto an upstream API spec, using rules by default
and optional local NLP. Give it the upstream spec you must implement (for example FDX) and the
specs or sample responses of the APIs you call; it tells you, for every upstream field,
which downstream field fills it, what conversion it needs, how confident it is and why.
It also plans the downstream calls, maps error codes, and can execute the plan against
mock downstreams to check the assembled response. Schema validity alone does not prove
that the chosen fields have the right meaning.

Rules-only matching remains the default. Optional local NLP adds sentence embeddings
of field names and descriptions to discover and score meaning-based candidates.
The rules-only mode gives the same output for the same inputs.

## Local NLP

Install the optional dependency in this checkout's environment:

```bash
.venv/bin/python -m pip install -e ".[nlp]"
```

Provision a trusted Sentence Transformers sentence-similarity model in a local folder
before enabling NLP. Model acquisition is a separate setup step; mapping never downloads
a model. Supply the complete saved model, including its tokenizer and pooling modules.

- **GUI:** Inputs → Decision thresholds → Local NLP model folder. Enter the folder's
  absolute path, Save, then Run mapping. Clear the path to return to rules only.
- **CLI:** append `--nlp-model /absolute/path/to/model` to `api-mapper map`.
- **Python:** pass `nlp=NlpSettings(model_path="/absolute/path/to/model")` to
  `MappingPipeline` (import settings from `api_mapper.matching.semantic`).

The encoder runs on CPU with `local_files_only=True` and `trust_remote_code=False`.
API content is encoded locally. These options follow the
[Sentence Transformers model API](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html).
A missing dependency, missing model folder or encoding failure fails the requested run
with a clear error, rather than silently changing matching modes.

Embeddings use split field paths and at most 80 description words, without sample payload
values. Distinct texts are encoded once per run. Retrieval adds at most ten semantic
candidates per target with cosine similarity of at least 0.80; these are configurable
through `NlpSettings` or the settings API's nested `nlp` object (`top_k`, `min_similarity`).
Cosine similarity appears as `local_nlp` evidence in the GUI, JSON and Excel. Its
weight is 0.20 only when it raises confidence; otherwise its weight is zero so that
weak similarity cannot dilute supported rule matches. `rules_score` records confidence
before NLP. Type vetoes and existing penalties remain in the evidence.

Candidates discovered only through NLP, or pushed over the automatic threshold by
NLP, require review. If no candidate reaches the review threshold, strong descriptive
similarity can still surface a candidate for review when types and array depths agree
and there are no role, collection, enum, reachability or other conflict penalties.
This exception tolerates a missing lexical anchor or guessed spelling; it does not
raise the recorded rule confidence. The decision notes explain the exception.

NLP scores are similarity signals, not probabilities. Accuracy and timing figures below
describe rules-only matching. Evaluate a chosen model against your own answer key before
relying on its rankings. NLP reproducibility requires the same model files, dependency
versions and runtime; byte-identical output across runtimes is not promised.

## Quick start

```bash
cd api-mapper
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
```

GUI (opens on http://127.0.0.1:8765, press **Load example** then **Run mapping**):

```bash
.venv/bin/api-mapper serve
```

Command line, writing `output/mapping-report.xlsx` and `.json`:

```bash
.venv/bin/api-mapper map --upstream samples/upstream/fdx/core-exchange-6.4.yaml --downstream samples/downstream/*/openapi.* samples/downstream/deposits/swagger.json samples/downstream/routing/manifest.yaml --errors samples/upstream/fdx/error-catalog.yaml --answer-key samples/answer_key.yaml
```

Tests (unit, golden accuracy, mutation stress, 50-API scale):

```bash
.venv/bin/python -m pytest -q
```

## Inputs

| Input | Formats |
|---|---|
| Upstream spec | OpenAPI 3.0/3.1 or Swagger 2.0, YAML or JSON, or a schema-only fragment (`components/schemas` or `definitions`) |
| Downstream specs | Same formats. Local `$ref`s to other files work when the files sit together (upload them together in the GUI) |
| Spec-less downstreams | Captured JSON responses plus a small manifest (see `samples/downstream/routing/manifest.yaml`), or uploaded per endpoint in the GUI |
| Error catalog | Upstream error codes with HTTP status and keywords (`samples/upstream/fdx/error-catalog.yaml`) |
| Extra lexicon | Your own abbreviations and synonyms, merged over `lexicon/finance.yaml` |
| Answer key | Optional expected mappings; turns on the accuracy report |

## What you get

- **Mappings**: every upstream field with status `auto`, `review`, `unmapped`, `derived`
  (discriminator values fixed by the variant), `manual` or `rejected`, the chosen source,
  up to five alternatives, the transforms, and the evidence for each candidate.
- **Transforms**: casts, minor units to decimal (`139902` → `1399.02`), epoch milliseconds
  to ISO timestamps, `yyyyMMdd` to ISO dates, timestamp to date, and enum value maps
  (`DDA` → `CHECKING`, `D` → `DEBIT`, `POA` → `POWER_OF_ATTORNEY`). Values with no
  counterpart are listed, never guessed.
- **Call plan** per upstream endpoint: which downstream calls, in what order, where each
  input comes from (the request, or a field returned by an earlier call), which calls fan
  out once per item, which run only for one variant, and inputs nobody supplies.
- **Error mapping**: each downstream error response to the upstream status and code.
- **Validation**: executes a plan against mock downstreams built from the specs' own
  examples (or synthesised from their schemas), with injectable latency and failures, and
  checks the assembled response against the upstream schema.
- **Reports**: the GUI, an Excel workbook (Summary, Field Mapping, Needs Review, Gaps,
  Transforms, Call Plan, Error Codes, Run Log) and JSON.

Manual decisions (accept, reject, choose another source) are saved in
`projects/default/overrides.json` and replayed on every run; decisions that no longer
apply are reported, not dropped.

## How matching works

Every schema is flattened into leaf fields. `oneOf` branches become variants, so
`accountId` inside `LoanAccount` and inside `DepositAccount` are separate targets that can
come from different APIs. Each field is then read into concepts with
`lexicon/finance.yaml`: identifiers are split (`debitAccount.id`, `int_rate_pct`,
`IBANNumber`), abbreviations expanded, phrases rewritten (`ledger balance` → current
balance) and synonyms merged. Spellings the lexicon has never seen are read against the
lexicon and the upstream spec's own words by consonant skeleton or unique prefix
(`blnc` → balance, `entri` → entry), and every such guess is shown in the evidence.

Each upstream field is compared with the downstream fields that share a concept or are
spelled alike. A pair is scored as a weighted mean of independent signals:

| Signal | What it checks |
|---|---|
| name | concept overlap, weighted by rarity, with partial credit for related concepts; a target's description can define its name ("bankId: the routing transit number") |
| spelling | string similarity of the normalised names |
| type | type and format compatibility, including the conversions above |
| enum | how many enum values map, from declared enums or values seen in samples |
| sample | whether example values have the same shape |
| description | whether one field's name appears in the other's description |
| structure, context, endpoint | array depth, the parent object, and the endpoint's resource |
| qualifier | both sides belong to the same account family (deposit, credit, loan…) |

The score is then multiplied down by penalties, each with a stated reason:

| Penalty | Example it prevents |
|---|---|
| different account family | `debitAccount.id` as a line-of-credit `accountId` |
| role words on one side | `fromAccountId` as `accountId` |
| conflicting modifiers | `lastPayment.amount` as `minimumPaymentAmount`; plain `amount` as `foreignAmount` |
| source never mentions what the target is about | `rail` as `bankId` just because both sit under "network" |
| items of a different collection | `transfers[].amount` as `transactions[].amount` |
| unreachable for this record | a bank-wide `/address-changes` list as one account's addresses |
| list into one value, per-item detail calls | taking the first of many, or calling a detail endpoint per list item |
| echoed input | `acctNum` returned by `/routing/{acctNum}` as the account number |
| incompatible samples, no shared enum value, deprecated source | |

A veto (for example a boolean into a date) zeroes the score but keeps the candidate, so
the report can say why an obvious-looking match was refused.

Decisions: at or above 0.72 a mapping is `auto` unless a different candidate is within
0.03 (then `review`); from 0.50 it is `review`; below it stays `unmapped`. When two
upstream fields of one record claim the same source, the weaker one goes to review.
Thresholds are adjustable in the GUI. Additional array levels, unproven numeric/date
conversions, mostly unmapped enums, and role-qualified IDs without identifier evidence
require review even when their names score highly.

## Measured accuracy

Ground truth is `samples/answer_key.yaml`, written before the matcher existed.

| Scenario | Precision of automatic decisions | Expected mappings surfaced |
|---|---|---|
| FDX 6.4 against the eight Northwind APIs, including a decoy API | 100% (0 wrong of 183) | 100% (84% automatically) |
| Same, every downstream renamed with lexicon abbreviations, synonyms and casing (8 seeds) | 100% | 100% |
| Same, renamed with spellings no lexicon lists: dropped vowels, truncation, reversed word order, filler words (16 seeds) | 100% | 74–98% |
| Same, plus 42 generated noise APIs sharing generic field names (50 APIs) | 100% | 100% |

Missed mappings land in review or unmapped; the tests fail on any wrong automatic
decision beyond a stated budget. A real public spec (UK Open Banking Account and
Transaction API, 2,898 fields) loads and maps in about 2.5 seconds.

Speed: 8 APIs 0.25 s, 50 APIs 0.9 s, 200 APIs 3.4 s on a laptop, against FDX's 351 fields.

### Real financial API validation

The [public-contract benchmark](samples/real-contracts/README.md) compares 99 labelled
FDX cases with pinned UK Open Banking and Plaid contracts (10 operations, 716 source
fields). Request-body context and explicit financial meanings raise correct origins
from 22 to 31 of 48 labelled origins for both rules and local MiniLM NLP. There are
zero incorrect automatic origins, nine missed origins and 21 incorrect review
suggestions (previously 18). Nine origins are automatic, one with an additional
condition. Body-dependent suggestions require review. These results do **not** establish
FDX parity. NLP helps the separate semantic challenge set, but adds no correct origins
on this financial-contract development benchmark.

Run `.venv/bin/python tools/validate_contracts.py`, optionally adding
`--nlp-model /absolute/path/to/model`. The JSON report lists every graded field and the
remaining conditions. The fixtures and ordinary contract tests require no network or
model download.

## Layout

```
src/api_mapper/
  models/        plain dataclasses: specs, fields, profiles, mappings, transforms, plans, errors
  loaders/       YAML/JSON parsing, $ref resolution, OpenAPI/Swagger/fragment loading, sample inference
  normalize/     flattener, tokenizer, lexicon, spelling resolver, field profiler
  matching/      signals, similarity, scorer, candidate index, optional local NLP, reachability, assigner, engine
  transforms/    type fit and conversion inference, enum value mapping, applying transforms
  errors/        error catalog and downstream error mapping
  planning/      call planner
  validation/    mock downstreams, response assembly, schema checks, plan executor
  evaluation/    answer keys and grading
  reporting/     Excel and JSON reports
  pipeline/      orchestrator with progress events, overrides
  api/           FastAPI backend for the GUI, workspace storage
  cli.py
web/             GUI: plain HTML, CSS and ES modules, no build step
lexicon/         finance.yaml, the only source of domain knowledge
samples/         FDX upstream, Northwind downstreams, error catalog, answer key
tests/           unit/, golden/, stress/
```

## Extending

- **New vocabulary**: add abbreviations, synonyms, phrases, related concepts or account
  families to `lexicon/finance.yaml`, or upload an extra lexicon in the GUI. This is the
  main lever for a new domain. `meaning_rules` distinguish explicit field meanings by
  concept, name phrase and leading-definition phrase; unknown meanings incur no
  penalty. These constraints apply to both rules and NLP.
- **Error codes**: list them in an error catalog with keywords.
- **Accuracy checks**: write an answer key in the format of `samples/answer_key.yaml` and
  pass `--answer-key`, or upload it in the GUI.

## Limits

- Mapping remains response-oriented. JSON request-body scalars and scalar arrays can
  bind to exact, type/format-compatible upstream inputs, including nested account
  filters. Credentials and unmatched required inputs need caller context; ambiguous
  objects/unions are not inferred. Body-dependent origins and chains require review
  of identifier compatibility and record selection.
- Mock validation sends JSON body bindings separately from path/query inputs and blocks
  calls missing required inputs. This is not full request-schema validation or proof
  that a real downstream honors a filter. Generic mocks do not implement filtering.
- Many-to-one transforms (concatenating first and last name) are not inferred; choose the
  source manually and note it.
- Remote `$ref`s (http URLs) are not fetched.
- The GUI keeps the latest run in memory; after a server restart, press Run again
  (uploaded files and overrides persist).
- Variant routing during validation only uses enum evidence from calls already made; when
  data cannot rule a variant out, its calls are made too and reported.
# api-upstream-mapper
# api-upstream-mapper
