---
name: hf-llm-trainer
description: Fine-tune open-source LLMs on HuggingFace infrastructure
---
# HuggingFace LLM Trainer

## Overview
Teaches Claude to fine-tune open-source LLMs end-to-end using HuggingFace Jobs.

## Installation
```bash
/plugin install hf-llm-trainer@huggingface-skills
```

## Capabilities
- **Training Methods:** SFT, DPO, GRPO (used for DeepSeek R1)
- **Model Sizes:** 0.5B to 70B parameters
- **Output:** GGUF conversion for local deployment

## Hardware Mapping
| Model Size | Hardware | Method |
|------------|----------|--------|
| <1B | t4-small | Full fine-tune |
| 1-3B | t4-medium | Full or LoRA |
| 3-7B | a10g-large | LoRA recommended |
| 7B+ | a10g-large | LoRA required |

## Usage Examples
```
# Quick test run
Do a quick test run to SFT Qwen-0.6B with 100 examples of my-org/support-conversations

# Production training
SFT Qwen-0.6B for production on full dataset. Checkpoints every 500 steps, 3 epochs.

# Dataset validation
Check if my-org/conversation-data works for SFT training
```

## Dataset Validation Output
```
SFT: ✓ READY - Found 'messages' column
DPO: ✗ INCOMPATIBLE - Missing 'chosen'/'rejected' columns
```

## Best Practices
- ✅ Always run demo ($0.50) before production ($30+)
- ✅ Validate dataset format first
- ✅ Use LoRA for 7B+ models
- ❌ Don't skip test runs
