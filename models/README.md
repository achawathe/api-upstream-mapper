# Local NLP model

`all-MiniLM-L6-v2/` contains the tested model weights, tokenizer and pooling configuration.
They are ordinary Git files: `git clone` or `git pull` retrieves the complete model.
The upstream model card, Apache 2.0 license and exact revision/file hashes are included.

Install the app's optional NLP dependencies in your Python environment:

```sh
python -m pip install -e ".[nlp]"
```

For CLI mapping, add `--nlp-model models/all-MiniLM-L6-v2` when running from the repository root.
For the GUI, set **Local NLP model folder** to the absolute path of that directory.
Model inference runs locally; no model download is performed during mapping.
