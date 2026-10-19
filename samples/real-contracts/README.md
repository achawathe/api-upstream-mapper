# Public financial API contract benchmark

This benchmark checks **field origins**, including the exact API, endpoint and full
JSON path. It does not certify an FDX implementation or call a live bank.

The upstream is the existing Plaid Core Exchange 6.4 fixture (FDX subset). Downstreams
are pinned public contracts from [UK Open Banking](https://github.com/OpenBankingUK/read-write-api-specs)
and [Plaid](https://github.com/plaid/plaid-openapi). See `provenance.json` for commit
IDs, original download URLs, hashes and selected operations. The original contracts'
response schemas, enums, descriptions, examples and paths are unchanged. Only
unselected operations and unused components were removed; endpoint objects and all
716 flattened fields were compared against the original selected contracts.

UK Open Banking contributes accounts, account detail, balances, transactions, party
and statements (6 operations, 432 fields). Plaid contributes accounts, transactions,
Auth and Identity (4 operations, 284 fields). Each provider is evaluated separately
against all 351 FDX target fields. The answer key grades 99 selected cases: 50 UK and
49 Plaid. It covers deposit account lists/details, deposit transactions, UK statement
identifiers/descriptions and Plaid ACH identifiers. Other FDX variants are ungraded.

There are 48 source-bearing labels and 51 deliberate direct-field gaps. Labels
include accepted alternative endpoints, explanations and conditions. A correct origin
can still require account selection, a join, enum conversion, sign handling, or event
filtering. `conditional_automatic` counts correct-origin automatic suggestions that
still need such a condition checked; it must not be read as successful value parity.

## Run locally

```bash
.venv/bin/python tools/validate_contracts.py
.venv/bin/python tools/validate_contracts.py --nlp-model /absolute/path/to/model
.venv/bin/python -m pytest tests/golden/test_real_contracts.py -q
```

The first command requires no model. The second requires the optional NLP dependency
and a provisioned local Sentence Transformers model. Both use checked-in fixtures;
network connections are blocked by the runner during evaluation. The report defaults
to `output/real-contracts.json`. A successful process exit means evaluation completed,
not that every mapping was correct. Read the reported wrong, missed and conditional
counts. The tests prevent incorrect automatic origins on this labelled scope and
regressions below the measured coverage; they do not assert complete parity.

## Measured result, 2026-10-16

Using local `all-MiniLM-L6-v2`, revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`, default thresholds:

| Implementation | Correct origins / 48 | Incorrect automatic origins | Incorrect review suggestions |
|---|---:|---:|---:|
| Before changes, rules | 21 | 5 | 13 |
| Before changes, NLP | 21 | 4 | 12 |
| Earlier safeguards, rules | 22 | 0 | 18 |
| Earlier safeguards, NLP | 22 | 0 | 18 |
| Body context and meanings, rules | 31 | 0 | 21 |
| Body context and meanings, NLP | 31 | 0 | 21 |

The current modes have nine automatic origins, including one conditional origin.
They miss nine source-bearing labels, choose a wrong source for eight others, and
suggest a source for 13 of the 51 gaps; 38 gaps are correctly left unmapped. UK coverage
is 16/23, Plaid 15/25. Body context exposes useful origins but also more wrong review
suggestions (21 versus 18). The answer key and source fixtures are unchanged from the
previous 22/48 result. Moving an incorrect automatic choice into review improves safety,
not correctness.

NLP does not improve this financial-contract benchmark. It remains optional. Its
separate semantic challenge benchmark improves from 19/29 correct origins with rules
to 25/29 with NLP, but that does not establish performance on real financial contracts.

## Important gaps revealed

- Plaid scopes its requests through POST bodies. The mapper now recognizes nested
  account selectors and binds exact compatible inputs. Caller credentials, identifier
  compatibility and response selection remain review requirements, including dependent
  calls. POST context is not evidence of an already verified integration.
- UK balance values need selection by balance kind and direction. Several equally typed
  amount fields are not interchangeable.
- A transaction reference, a related transaction ID, booking time, value date and server
  ingestion time have different meanings. A name match is not sufficient evidence.
- A broad account category is not an account subtype; APY is not nominal interest rate.
- Long descriptions can dilute the embedding model. A local experiment combining the
  existing score with leading-definition embeddings added no correct origins (31/48
  both ways). Embedding text, model and thresholds were therefore left unchanged.
  Explicit meaning constraints use leading definitions without replacing embeddings.

The labels were manually authored from the contracts before the first matcher run.
During audit, UK merchant name was added as an allowed transaction description because
FDX expressly allows it; account-list targets were added to cover both list and detail
contexts. Baselines were rerun on the same final 99-label key. The benchmark informed
the fixes, so it is a development benchmark, not an untouched holdout or an independent
certification. An additional provider and independently reviewed labels are needed to
measure generalization.

The tests additionally project account IDs and masked account numbers from Plaid's
published response examples into FDX fields, verifying values, array lengths and field
types. These are example projections, not live API calls or full-response parity.
UK fixtures do not contain operation response examples; no live payload is claimed.
Additional unit tests use a strict in-memory HTTP transport to check JSON account
filters, credentials, missing-input handling and field projection. Generic published-
example mocks do not implement account filtering, and these tests do not claim that
real account selection or authentication was exercised.

## Source terms

The original source notices and `info` metadata remain in each fixture. UK Open Banking
publishes its specifications under its [Open Licence](https://www.openbanking.org.uk/open-licence/).
Plaid's contract and the existing Core Exchange/FDX fixture retain their original terms;
this benchmark does not grant additional rights or relicense those specifications.
