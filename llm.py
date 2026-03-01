import os
from huggingface_hub import InferenceClient

# Initialize with the provider name
client = InferenceClient(
    provider="featherless-ai",  # Specify provider here
    api_key=os.environ["HF_TOKEN"]
)

# Use only the base model ID
completion = client.chat.completions.create(
    model="mistralai/Mistral-7B-Instruct-v0.2",
    messages=[{"role": "user", "content": "Hello!"}],
    max_tokens=500
)

print(completion.choices[0].message)
