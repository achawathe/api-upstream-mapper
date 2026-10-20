"""Train exactly the requested JSON continuation, without template-inserted reasoning or post-EOS text."""

from experiments.local_reranker.runtime import read_rows


def completion_tokens(row, tokenizer):
    messages = row["messages"]
    prompt = tokenizer.apply_chat_template(
        messages[:-1], add_generation_prompt=True, return_dict=False, enable_thinking=False
    )
    answer = tokenizer.encode(messages[-1]["content"], add_special_tokens=False)
    return prompt + answer + [tokenizer.eos_token_id], len(prompt)


class SelectionDataset:
    def __init__(self, path, tokenizer):
        self.rows = read_rows(path)
        self.tokenizer = tokenizer

    def process(self, row):
        return completion_tokens(row, self.tokenizer)

    def __getitem__(self, index):
        return self.rows[index]

    def __len__(self):
        return len(self.rows)
