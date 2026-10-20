# Mapping downstream values into a channel contract

A channel API presents a contract shaped for its consumer. Its fields and value
sets can differ from the systems it calls. MuleSoft describes Experience APIs as
projecting data formats and interactions into a particular channel and context:
[Experience API ownership](https://blogs.mulesoft.com/api-integration/strategy/experience-api-ownership/).
Microsoft's [Backends for Frontends pattern](https://learn.microsoft.com/en-us/azure/architecture/patterns/backends-for-frontends)
similarly separates client-specific requirements from shared backend services.
This layer is useful when consumers need different contracts; every application
does not need a separate channel layer.

For this mapper, the upstream response schema is the channel's required output.
The downstream fields are its data sources. Mapping needs to record both:

1. Which provider field supplies the channel field.
2. How that provider's representation becomes an allowed channel value.

For example, provider strings `in progress` and `packing` may both become the
channel status `PROCESSING`. A similar field name does not establish that meaning;
the translation needs a definition or a reviewer decision. Request routing,
business orchestration and deploying a channel API remain outside this feature.

## Normalize to allowed values

The Blocks editor's **Normalize to allowed values** conversion replaces the generic
value-translation inputs with allowed output choices when a value set is available.
Each source string maps to one output; several source strings may map to the same
output. Sources come from declared values, sample observations, schema examples and
explicit documented aliases. Aliases may be attached to either the upstream or
downstream API; their outputs must belong to the channel's allowed set. Conflicting
translations across the two APIs remain unresolved, even if spelling alone would
suggest a match. Existing heuristic suggestions still need review.

The allowed output set comes from the target OpenAPI enum first. If no enum is
declared, an explicit list in its field description or attached documentation may
supply the set. The editor labels the origin and shows document citations. It does
not rewrite the uploaded schema. Conflicting documents are flagged rather than
unioned; documentation cannot expand or override a declared schema enum.

Choose how incoming strings are compared:

- **Exact strings** preserves case, whitespace and separators.
- **Trim spaces and ignore case** normalizes outer whitespace and case only.
- **Also treat spaces, hyphens and underscores alike** collapses those separators.

These modes only normalize the keys in the reviewed translation table. They do not
guess semantic equivalents. If two keys normalize to the same spelling but select
different outputs, preview and save reject the ambiguity.

An unlisted string produces a conversion error by default. The reviewer may choose
an explicit fallback, but only from the allowed output set. Null remains null; the
output field's requiredness/nullability rules are still checked. Non-string input
needs a preceding type-conversion block. Preview uses the same conversion function
as mock validation. Save validates outputs against the current target contract;
reruns ignore obsolete manual overrides with a warning if their values are no
longer allowed.

## Documentation format

Use endpoint headings and name the field on each definition line:

```text
GET /orders
status: Allowed values: PROCESSING, COMPLETED, FAILED, UNKNOWN.
status: "in progress" -> "PROCESSING"; "packing" -> "PROCESSING"; "done" -> "COMPLETED".
```

The current reader supports explicit comma/pipe-separated lists with uppercase
unquoted values or quoted text values, and quoted `->`, `→` or `maps to`
translations. General prose, illustrations and arbitrary document tables are not
automatically interpreted as exhaustive value sets. Documentation may be pasted
or extracted locally from the supported text/PDF/DOCX formats. Alias extraction is
field/endpoint scoped and conflicting aliases remain unresolved.

Everything executes locally. This is contract-aware conversion, not a fine-tuned
model or an LLM classifying new strings at runtime. Local NLP can assist field
selection; the saved conversion table determines actual output values.

## Try the example

Upload `samples/channel-enums/channel.yaml` as upstream and `provider.yaml` as
downstream, then attach `channel-guide.md` to the upstream. Select General
applications and run mapping. Orders use a specification enum; shipments use a
documented enum. Both include explicit aliases and remain review suggestions.
These are synthetic feature tests, not evidence of a real provider's behavior.
