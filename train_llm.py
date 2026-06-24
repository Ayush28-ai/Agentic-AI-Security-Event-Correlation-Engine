import torch
from datasets import load_dataset
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    Trainer,
    TrainingArguments,
    DataCollatorForLanguageModeling,
    BitsAndBytesConfig
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

print(f"CUDA available: {torch.cuda.is_available()}")

MODEL_NAME = "microsoft/Phi-3-mini-4k-instruct"

# ----------------------------
# Load Dataset
# ----------------------------
dataset = load_dataset("json", data_files="data/train.jsonl", split="train")
print(f"Dataset size: {len(dataset)}")

# ----------------------------
# Tokenizer
# ----------------------------
tokenizer = AutoTokenizer.from_pretrained(
    MODEL_NAME,
    trust_remote_code=True
)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

# ----------------------------
# 8-bit quantization config
# ----------------------------
bnb_config = BitsAndBytesConfig(
    load_in_8bit=True,
    llm_int8_threshold=6.0,
    llm_int8_has_fp16_weight=False
)

# ----------------------------
# Load quantized model
# ----------------------------
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    quantization_config=bnb_config,
    trust_remote_code=True,
    attn_implementation="eager",
    use_cache=False
)

# ✅ Step 1: Prepare quantized model for training
model = prepare_model_for_kbit_training(model)

# ✅ Step 2: Attach LoRA adapters — only these are trained, not the full model
lora_config = LoraConfig(
    r=8,                          # LoRA rank — higher = more capacity, more VRAM
    lora_alpha=16,                # scaling factor
    target_modules=[              # Phi-3 attention projection layers
        "o_proj",
        "qkv_proj"
    ],
    lora_dropout=0.05,
    bias="none",
    task_type="CAUSAL_LM"
)

model = get_peft_model(model, lora_config)
model.print_trainable_parameters()  # shows how few params are actually trained

# ----------------------------
# Preprocessing
# ----------------------------
def preprocess(example):
    prompt = (
        f"<|system|>\n"
        f"You are a SOC AI Analyst. Output only valid JSON.\n"
        f"<|end|>\n"
        f"<|user|>\n"
        f"{example['prompt']}\n"
        f"<|end|>\n"
        f"<|assistant|>\n"
        f"{example['completion']}\n"
        f"<|end|>"
    )
    tokens = tokenizer(
        prompt,
        truncation=True,
        max_length=512,
        padding="max_length"
    )
    tokens["labels"] = tokens["input_ids"].copy()
    return tokens

tokenized_ds = dataset.map(
    preprocess,
    remove_columns=dataset.column_names
)

# ----------------------------
# Data Collator
# ----------------------------
data_collator = DataCollatorForLanguageModeling(
    tokenizer=tokenizer,
    mlm=False
)

# ----------------------------
# Training Args
# ----------------------------
training_args = TrainingArguments(
    output_dir="./soc_llm_phi3",
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    num_train_epochs=3,
    learning_rate=2e-4,           # ✅ higher LR works better for LoRA
    logging_steps=1,
    save_steps=50,
    save_total_limit=2,
    fp16=False,                   # ✅ must be False with 8-bit quant
    bf16=False,
    optim="adamw_torch",
    report_to="none",
    warmup_steps=5,
    gradient_checkpointing=False, # ✅ False with LoRA — not needed
    dataloader_pin_memory=False
)

# ----------------------------
# Trainer
# ----------------------------
trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=tokenized_ds,
    data_collator=data_collator,
    tokenizer=tokenizer
)

print("Starting training...")
trainer.train()

# ✅ Save LoRA adapters + tokenizer
model.save_pretrained("./soc_llm_phi3")
tokenizer.save_pretrained("./soc_llm_phi3")
print("Training complete.")