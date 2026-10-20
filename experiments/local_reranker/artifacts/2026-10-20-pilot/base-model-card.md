---
library_name: mlx
license: apache-2.0
license_link: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507/blob/main/LICENSE
pipeline_tag: text-generation
tags:
- mlx
base_model: Qwen/Qwen3-4B-Instruct-2507
---

# mlx-community/Qwen3-4B-Instruct-2507-4bit

This model [mlx-community/Qwen3-4B-Instruct-2507-4bit](https://huggingface.co/mlx-community/Qwen3-4B-Instruct-2507-4bit) was
converted to MLX format from [Qwen/Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507)
using mlx-lm version **0.26.2**.

## Use with mlx

```bash
pip install mlx-lm
```

```python
from mlx_lm import load, generate

model, tokenizer = load("mlx-community/Qwen3-4B-Instruct-2507-4bit")

prompt = "hello"

if tokenizer.chat_template is not None:
    messages = [{"role": "user", "content": prompt}]
    prompt = tokenizer.apply_chat_template(messages, add_generation_prompt=True)

response = generate(model, tokenizer, prompt=prompt, verbose=True)
```
