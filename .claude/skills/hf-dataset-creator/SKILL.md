---
name: hf-dataset-creator
description: Create structured training datasets for HuggingFace
---
# HuggingFace Dataset Creator

## Overview
Prompts, templates, and scripts for creating structured training datasets.

## Dataset Formats

### SFT (Supervised Fine-Tuning)
```json
{
  "messages": [
    {"role": "user", "content": "Question"},
    {"role": "assistant", "content": "Answer"}
  ]
}
```

### DPO (Direct Preference Optimization)
```json
{
  "prompt": "Question",
  "chosen": "Better answer",
  "rejected": "Worse answer"
}
```

### GRPO (Group Relative Policy Optimization)
```json
{
  "prompt": "Question",
  "responses": ["Answer1", "Answer2", "Answer3"],
  "scores": [0.9, 0.7, 0.3]
}
```

## Usage
```
Create a SFT dataset from my customer support logs
Convert my CSV to DPO format for preference training
```

## Best Practices
- ✅ Include diverse examples
- ✅ Balance positive/negative cases
- ✅ Validate format before training
- ❌ Don't use < 100 examples
