---
name: hf-model-evaluator
description: "Evaluate LLM performance with metrics and benchmarks. Use when assessing model quality."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# HuggingFace Model Evaluator

## Basic Evaluation
```python
from evaluate import load

# Perplexity
perplexity = load("perplexity", module_type="metric")
results = perplexity.compute(predictions=predictions, model_id="gpt2")

# BLEU score
bleu = load("bleu")
results = bleu.compute(predictions=preds, references=refs)

# ROUGE score
rouge = load("rouge")
results = rouge.compute(predictions=preds, references=refs)
```

## Classification Metrics
```python
from evaluate import combine

clf_metrics = combine(["accuracy", "f1", "precision", "recall"])
results = clf_metrics.compute(predictions=preds, references=labels)
```

## LLM Evaluation Pipeline
```python
from transformers import pipeline

# Text generation evaluation
generator = pipeline("text-generation", model="your-model")

test_prompts = [
    "Summarize: ...",
    "Translate: ...",
    "Answer: ..."
]

for prompt in test_prompts:
    output = generator(prompt, max_length=100)
    print(f"Prompt: {prompt}")
    print(f"Output: {output[0]['generated_text']}")
```

## Custom Evaluation
```python
def evaluate_model(model, tokenizer, test_data):
    results = []
    
    for example in test_data:
        inputs = tokenizer(example["input"], return_tensors="pt")
        outputs = model.generate(**inputs, max_new_tokens=100)
        generated = tokenizer.decode(outputs[0], skip_special_tokens=True)
        
        results.append({
            "input": example["input"],
            "expected": example["output"],
            "generated": generated,
            "match": generated.strip() == example["output"].strip()
        })
    
    accuracy = sum(r["match"] for r in results) / len(results)
    return {"accuracy": accuracy, "results": results}
```
