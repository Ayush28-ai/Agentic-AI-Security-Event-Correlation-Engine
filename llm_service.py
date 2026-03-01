from fastapi import FastAPI
from pydantic import BaseModel
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import torch

MODEL_PATH = "./soc_llm_flan_t5"

tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSeq2SeqLM.from_pretrained(
    MODEL_PATH,
    device_map="auto" if torch.cuda.is_available() else None
)

app = FastAPI()

class LLMRequest(BaseModel):
    prompt: str

@app.post("/analyze")
def analyze(req: LLMRequest):
    inputs = tokenizer(req.prompt, return_tensors="pt").to(model.device)

    outputs = model.generate(
        **inputs,
        max_length=300,
        do_sample=False
    )

    return {
        "analysis": tokenizer.decode(outputs[0], skip_special_tokens=True)
    }
