---
name: hf-model-deployer
description: "Deploy models to HuggingFace Inference Endpoints. Use when deploying models for production."
allowed-tools: "Read,Write,Bash"
version: 1.0.0
---

# HuggingFace Model Deployer

## Inference Endpoints
```python
from huggingface_hub import create_inference_endpoint

endpoint = create_inference_endpoint(
    name="my-model-endpoint",
    repository="username/my-model",
    framework="pytorch",
    task="text-generation",
    accelerator="gpu",
    instance_size="medium",
    instance_type="nvidia-a10g",
    region="us-east-1",
    vendor="aws"
)

# Wait for deployment
endpoint.wait()
print(f"Endpoint URL: {endpoint.url}")
```

## Query Endpoint
```python
from huggingface_hub import InferenceClient

client = InferenceClient(model="username/my-model")

# Text generation
response = client.text_generation(
    "Once upon a time",
    max_new_tokens=100,
    temperature=0.7
)

# Chat completion
response = client.chat_completion(
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=500
)
```

## Gradio Demo
```python
import gradio as gr
from transformers import pipeline

pipe = pipeline("text-generation", model="username/my-model")

def generate(prompt, max_length=100):
    return pipe(prompt, max_length=max_length)[0]["generated_text"]

demo = gr.Interface(
    fn=generate,
    inputs=[
        gr.Textbox(label="Prompt"),
        gr.Slider(50, 500, value=100, label="Max Length")
    ],
    outputs="text",
    title="My Model Demo"
)

demo.launch()
```

## Spaces Deployment
```yaml
# README.md in Spaces repo
---
title: My Model Demo
emoji: 🚀
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.0.0
app_file: app.py
pinned: false
---
```
