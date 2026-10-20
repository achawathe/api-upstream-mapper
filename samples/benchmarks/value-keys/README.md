# Benchmark: value keys in sample JSON

Spec-less downstream APIs, known only from captured JSON, where some object keys are data
(cities, currency codes, account IDs) rather than field names, plus decoys that share words
with the targets and one fixed-key object that must stay an ordinary object.
`answer_key.yaml` was written before the matcher could read value keys; see
`PLAN-data-first.md` (B1). All data here is invented for the benchmark.
