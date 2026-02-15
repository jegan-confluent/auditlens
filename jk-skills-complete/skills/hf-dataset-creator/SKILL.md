---
name: hf-dataset-creator
description: "Create and upload datasets to HuggingFace Hub. Use when preparing training data."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# HuggingFace Dataset Creator

## Create Dataset from JSON
```python
from datasets import Dataset, DatasetDict

# From list of dicts
data = [
    {"text": "Hello world", "label": 0},
    {"text": "Goodbye world", "label": 1}
]
dataset = Dataset.from_list(data)

# From pandas
import pandas as pd
df = pd.read_csv("data.csv")
dataset = Dataset.from_pandas(df)
```

## Instruction Format
```python
def format_instruction(example):
    return {
        "text": f"""### Instruction:
{example['instruction']}

### Input:
{example['input']}

### Response:
{example['output']}"""
    }

dataset = dataset.map(format_instruction)
```

## Train/Test Split
```python
dataset_dict = dataset.train_test_split(test_size=0.1, seed=42)
# Creates DatasetDict with 'train' and 'test' splits
```

## Upload to Hub
```python
from huggingface_hub import login
login(token="hf_xxx")

dataset.push_to_hub(
    "username/my-dataset",
    private=False,
    token="hf_xxx"
)
```

## Dataset Card
```python
# Create README.md in dataset repo
DATASET_CARD = """
---
license: mit
task_categories:
  - text-classification
language:
  - en
size_categories:
  - 1K<n<10K
---

# My Dataset

## Description
Description of your dataset...

## Usage
```python
from datasets import load_dataset
dataset = load_dataset("username/my-dataset")
```
"""
```
