# Local mapping accuracy: diagnosis and fixes

The investigated failures came from lost input context, incomplete ownership checks
and missing definition relationships. Changing models alone did not repair them.
The app continues to use its existing local MiniLM model; no new weights are deployed.

## Reproduced causes

1. **Scalar-list flattening discarded the property description.** For Plaid
   `item.products[]`, the list's description says these are products added to the
   API Item. Flattening retained only the referenced generic `Products` description.
   The distinction from an account's marketed product was lost before either rules
   or NLP saw it. Flattening now preserves the property definition while retaining
   the item's type and enum constraints. The finance vocabulary recognizes API Item
   products as a different meaning from marketed bank products.
2. **Ownership checking returned true immediately for a scalar target.** An FDX
   account currency could therefore select `transactions[].iso_currency_code` over
   `accounts[].balances.iso_currency_code`. A known target endpoint resource now
   supplies the missing record context. A mismatched source collection receives
   the existing collection penalty and cannot use contextual rescue. This is a
   compatibility signal, not proof that the correct account has been selected.
3. **Definition support was absent from discovery and selection.** Plaid's official
   name had local similarity about 0.56 and its user-assignable name about 0.52;
   neither met the 0.80 semantic threshold. Official name could enter the candidate
   index through shared context, but had insufficient evidence at the scoring gate;
   nickname's source did not enter the index. Bounded, configurable purpose rules
   now relate official/marketed names and distinguish them from nicknames and IDs.
   Eligible explicit definition matches take precedence over spelling, with their
   original numeric scores retained and mandatory human review. Value shape alone
   does not get this precedence.
4. **API upload classification was not mutually exclusive.** A downstream OpenAPI
   file with `components` was registered both as an API and as a schema fragment.
   This duplicated its candidate pool, and attached samples belonged only to one
   copy. Entrypoint discovery now classifies API files once while retaining separate
   standalone fragments. This fixes new uploads; existing saved duplicate inputs
   are not automatically removed.
5. **Model attachments had no separate input flow.** The loader already supported
   local external references when the files were uploaded together. Uploading models
   later through the upstream-spec control could replace the API with a schema
   fragment. The optional model-files control now attaches to the existing API ID,
   preserves its examples, resolves matching filenames and refreshes its warnings.
   Uploads are validated in a separate bundle before replacing the active path.

The shared review eligibility check allows a source field inside one list of the
same record kind to be suggested for a scalar target. It retains the list-selection
penalty and review note. It does not waive incompatible types, primitive lists,
different record collections, nested array depth, role conflicts, enum conflicts,
unreachable calls or conflicting definitions. Unknown endpoint names do not establish
record ownership. The similarity threshold remains 0.80.

## Focused development check

Six fields were selected before editing: four demonstrated failures and two working
controls. All 284 downstream fields remain available; no expected source is injected
into discovery. Inputs are the pinned FDX Core Exchange 6.4 and Plaid contracts in
`samples/`, with their published response examples attached as documentation.

| FDX field | Before | After |
|---|---|---|
| productName | API Item product | Account official name, review |
| nickname | Unmapped | User-assignable account name, review |
| productId | API Item product | Unmapped: no supported source |
| currency.currencyCode | Transaction currency | Account balance currency, review |
| accountId | Correct account ID | Preserved, review |
| currentBalance | Correct account balance | Preserved, review |

Both rules and actual local MiniLM improve from 2/6 to 6/6 correct decisions.
This comprises five correct origins and one correct abstention. Network access was
blocked during the focused model check. These are development regressions, not an
unseen accuracy estimate. The gain is attributable to pipeline and vocabulary fixes;
it does not demonstrate additional accuracy from MiniLM on this slice or successful
weight fine-tuning. Provider record binding and identity selection still require review.

## Validation

The regression suite preserves existing golden accuracy budgets. New tests reproduce
lost list definitions, duplicated API registration, account-versus-transaction scope,
definition matches despite renamed fields, and product IDs versus labels. Final
end-to-end validation uses the full real contracts through the local app, its actual
MiniLM runtime, progress events, comparison view, activity log and JSON/Excel reports.
It does not call authenticated bank endpoints or establish full FDX parity.

Final result: **257 tests passed**, with one existing Starlette deprecation warning.
The browser run used the real FDX schema split into an API file and a model file:
11 unresolved-reference warnings before attachment, zero afterward, 351 upstream
fields and 284 downstream fields processed with actual local MiniLM. All six focused
decisions matched their expected origins/abstention in that full app run. Progress,
activity logging, comparison text and both reports were verified; the browser reported
no console errors. Invalid attachment and missing-pointer tests confirm that unresolved
problems are not hidden merely because a model file was supplied.

## Subsequent full-contract refinement

The next diagnosis found permissive plain-text/date compatibility and missing
requirements for masked account numbers, foreign currency, classification systems
and related transaction identifiers. Declarative origin requirements now prevent
similar words from overriding these distinctions. Account status definitions can
identify an origin while leaving unresolved enum translations for review.
Normalized name concepts preserve abbreviated and nested field names.

On the 99 labelled UK/Plaid cases, the immediate baseline was 37 correct origins,
13 wrong suggestions, seven missed origins and 42 correct abstentions. The refined
result is 40 correct origins, zero wrong suggestions, eight missed origins and all
51 correct abstentions. Nine origins are automatic, zero automatic origins are
wrong, and one automatic origin still has a conditional record-binding limitation.
Rules and real local MiniLM produce the same result with networking blocked.
No model weights were trained. These cases informed development, so the result is
a regression result rather than a held-out accuracy estimate or live-bank parity.

The optional-documentation and visual-editor changes are described in
[documentation and editor](documentation-and-editor.md). The full suite passed
292 tests after the editor validation changes, including an additional regression
for resolved value translations. Pointer source connection and conversion-block
reordering were verified in the in-app browser.
