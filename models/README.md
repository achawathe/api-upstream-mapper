# Local NLP model

`all-MiniLM-L6-v2/` contains the tested model weights, tokenizer and pooling configuration.
They are ordinary Git files: `git clone` or `git pull` retrieves the complete model.
The upstream model card, Apache 2.0 license and exact revision/file hashes are included.
Git LFS, archives, extraction helpers and a separate model download are not required.
The binary attributes preserve identical bytes across Git line-ending settings.

Install the app's optional NLP dependencies in your Python environment:

```sh
python -m pip install -e ".[nlp]"
```

For CLI mapping, add `--nlp-model models/all-MiniLM-L6-v2` when running from the repository root.
For the GUI, set **Local NLP model folder** to the absolute path of that directory.
Model inference runs locally; no model download is performed during mapping.

## Existing checkouts

The 21 October 2026 update replaces LFS pointers with the original weight files in a
new commit; published history is preserved. A fresh clone of the current branch
needs only ordinary Git. Historical commits retain their original storage format.

An old checkout may still have local Git LFS hooks in `.git/hooks` that complain
when `git-lfs` is absent. Remove only the LFS-generated `pre-push`, `post-checkout`,
`post-commit` and `post-merge` hooks, preserving any custom hooks. If Git LFS is still
installed, `git lfs uninstall --local` performs the repository-local cleanup.
Fresh clones need no hook cleanup or LFS installation. Global settings used by
other repositories do not need to change.
