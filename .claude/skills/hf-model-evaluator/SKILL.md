---
name: hf-model-evaluator
description: Evaluate LLM performance and generate reports
---
# HuggingFace Model Evaluator

## Overview
Orchestrate evaluation jobs, generate reports, and map metrics.

## Evaluation Types
- **Accuracy:** Task completion rate
- **Perplexity:** Language model quality
- **BLEU/ROUGE:** Text generation quality
- **Custom:** Domain-specific metrics

## Usage
```
Evaluate my fine-tuned model against the base model
Run benchmark suite on my-org/custom-model
Generate comparison report for models A vs B
```

## Metrics Dashboard
```python
from evaluate import load
accuracy = load("accuracy")
results = accuracy.compute(predictions=preds, references=refs)
```

## Best Practices
- ✅ Use held-out test set
- ✅ Compare against baseline
- ✅ Track metrics over training
