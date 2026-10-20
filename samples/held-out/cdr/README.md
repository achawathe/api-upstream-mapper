# Held-out benchmark: Australian Consumer Data Right

Unmodified CDR Banking and Common API specs (v1.36.0, MIT licence), pinned in
`provenance.json`. `answer_key.yaml` was written from the specs alone before the mapper
was first run on them.

This set exists to measure accuracy on an API the rules were not developed against.
Do not tune rules or lexicon entries to it. If a general fix also changes its result,
say so in the commit, because the set is then no longer untouched.
