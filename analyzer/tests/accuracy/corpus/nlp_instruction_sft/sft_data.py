"""Turn an instruction dataset into chat-templated, packed training text."""

from datasets import load_dataset

SEED = 4242
SYSTEM = "You are a careful assistant. Answer briefly and cite your reasoning."


def load_instructions(name="HuggingFaceH4/no_robots"):
    raw = load_dataset(name)
    return raw["train"], raw["test"]


def to_messages(row):
    return {
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": row["prompt"]},
            {"role": "assistant", "content": row["completion"]},
        ]
    }


def render(tokenizer, row):
    text = tokenizer.apply_chat_template(row["messages"], tokenize=False)
    return {"text": text}


def prepare(tokenizer, train_rows, eval_rows):
    train = train_rows.map(to_messages, remove_columns=train_rows.column_names)
    evaluation = eval_rows.map(to_messages, remove_columns=eval_rows.column_names)
    train = train.map(lambda row: render(tokenizer, row))
    evaluation = evaluation.map(lambda row: render(tokenizer, row))
    return train.shuffle(seed=SEED), evaluation
