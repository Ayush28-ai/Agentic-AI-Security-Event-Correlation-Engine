import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling
)

print(f"CUDA available: {torch.cuda.is_available()}")

MODEL_NAME = "TinyLlama/TinyLlama-1.1B-Chat-v1.0"

# ----------------------------
# Load Dataset
# ----------------------------
dataset = load_dataset("json", data_files="data/train.jsonl", split="train")
print(f"Dataset size: {len(dataset)}")

# ----------------------------
# Tokenizer
# ----------------------------
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
tokenizer.pad_token = tokenizer.eos_token

# ----------------------------
# Model
# ----------------------------
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    device_map="auto",
    torch_dtype=torch.float16
)

# ----------------------------
# Preprocessing
# ----------------------------
def preprocess(example):
    prompt = f"""
### Instruction:
You are a SOC AI Analyst.

### Input:
{example['prompt']}

### Response:
{example['completion']}
"""

    tokens = tokenizer(
        prompt,
        truncation=True,
        max_length=512
    )

    tokens["labels"] = tokens["input_ids"].copy()
    return tokens


tokenized_ds = dataset.map(
    preprocess,
    remove_columns=dataset.column_names
)

# ----------------------------
# Data collator
# ----------------------------
data_collator = DataCollatorForLanguageModeling(
    tokenizer=tokenizer,
    mlm=False
)

# ----------------------------
# Training args
# ----------------------------
training_args = TrainingArguments(
    output_dir="./soc_llm_tinyllama",
    per_device_train_batch_size=2,
    gradient_accumulation_steps=4,
    num_train_epochs=3,
    learning_rate=2e-5,
    logging_steps=10,
    save_steps=200,
    save_total_limit=2,
    fp16=True,
    optim="adamw_torch",
    report_to="none"
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_ds,
    data_collator=data_collator,
    tokenizer=tokenizer
)

print("Starting training...")
trainer.train()

trainer.save_model("./soc_llm_tinyllama")
tokenizer.save_pretrained("./soc_llm_tinyllama")

print("Training complete.")