import os
import torch
import threading
from fastapi import FastAPI
from contextlib import asynccontextmanager
from pydantic import BaseModel
from transformers import (
    AutoTokenizer, AutoModelForCausalLM,
    BitsAndBytesConfig, pipeline
)

BASE_MODEL = "microsoft/Phi-3-mini-4k-instruct"
_pipe      = None

# ── GPU LOCK ───────────────────────────────────────────────────────
# ROOT CAUSE OF YOUR TIMEOUT:
# /analyze (background enrichment, called every 30s per device) and
# /ask (user chat) both call _pipe() on the same GPU with no
# coordination. When /analyze is mid-inference (~30-60s), /ask
# queues behind it. Streamlit's 90s timeout expires before /ask
# gets its turn → dashboard shows "Rule-based" every time.
#
# Fix: one threading.Lock() for all inference. /ask and /analyze
# take turns. A user's /ask call will wait at most ~60s for a
# running /analyze to finish, then get its response.
# Combined with shorter token limits below, /ask now completes
# well within the 90s window.
_gpu_lock = threading.Lock()


def load_model():
    global _pipe

    tokenizer = AutoTokenizer.from_pretrained(
        BASE_MODEL, trust_remote_code=True
    )
    tokenizer.pad_token    = tokenizer.eos_token
    tokenizer.padding_side = "right"
    print(f"✅ Tokenizer ready (vocab={tokenizer.vocab_size})")

    bnb = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
        bnb_4bit_quant_type="nf4"
    )

    print("🔄 Loading Phi-3 4-bit NF4...")
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL,
        quantization_config=bnb,
        trust_remote_code=True,
        attn_implementation="eager",
        device_map="auto",
        torch_dtype=torch.float16
    )
    model.eval()
    print("✅ Model loaded")

    _pipe = pipeline(
        "text-generation",
        model=model,
        tokenizer=tokenizer,
        do_sample=True,
        temperature=0.3,
        top_p=0.9,
        repetition_penalty=1.1,
        return_full_text=False,
        trust_remote_code=True
    )
    print("✅ Pipeline ready")

    print("🔥 Warming up GPU...")
    try:
        with _gpu_lock:
            _pipe([{"role": "user", "content": "hi"}], max_new_tokens=5)
        print("✅ GPU warmed up")
    except Exception as e:
        print(f"⚠️  Warmup skipped: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield


app = FastAPI(title="SOC LLM Service", lifespan=lifespan)


class PromptRequest(BaseModel):
    prompt:      str
    max_tokens:  int = 150
    temperature: float = 0.3

class AskRequest(BaseModel):
    question: str
    context:  str = ""
    mode:     str = "analyst"


def clean(text: str) -> str:
    for tok in ["<|end|>", "<|endoftext|>", "<|assistant|>",
                "<|user|>", "<|system|>"]:
        text = text.replace(tok, "")
    return text.strip()


def run(messages: list, max_tokens: int, label: str = "") -> str:
    """
    Serialize all GPU inference through _gpu_lock.
    label is for logging only.
    """
    if _pipe is None:
        print("❌ Pipeline not ready")
        return ""
    print(f"⏳ {label} waiting for GPU lock...")
    with _gpu_lock:
        print(f"🔒 {label} acquired GPU lock — running inference")
        try:
            out    = _pipe(messages, max_new_tokens=max_tokens)
            raw    = out[0]["generated_text"]
            result = clean(
                raw[-1].get("content", "") if isinstance(raw, list)
                else str(raw)
            )
            print(f"✅ {label} done — {len(result)} chars: '{result[:60]}'")
            return result
        except Exception as e:
            print(f"⚠️  {label} inference error: {e}")
            return ""


SOC_SYSTEM = (
    "You are a SOC AI Analyst with access to live security incident data. "
    "Answer ONLY based on the data provided. "
    "Be direct and specific — name actual devices and risk levels. "
    "Keep your answer under 120 words."
)

GENERAL_SYSTEM = (
    "You are a SOC AI Analyst. Answer concisely. Under 80 words."
)


@app.post("/generate")
def generate(req: PromptRequest):
    out = run(
        [{"role": "user", "content": req.prompt}],
        max_tokens=req.max_tokens,
        label="/generate"
    )
    return {"output": out, "status": "ok" if out else "empty"}


@app.post("/ask")
def ask(req: AskRequest):
    """
    Dashboard chat endpoint.
    Reduced to max_new_tokens=150 so inference takes ~15-25s
    instead of 40-60s, fitting comfortably in the 90s timeout
    even when /analyze just finished.
    """
    ctx = req.context[:500].strip() if req.context else ""

    system   = SOC_SYSTEM if ctx else GENERAL_SYSTEM
    user_msg = (
        f"INCIDENT DATA:\n{ctx}\n\nQUESTION: {req.question}\nAnswer:"
        if ctx else req.question
    )

    print(f"📥 /ask: '{req.question[:60]}' ctx={len(ctx)}ch")

    out = run([
        {"role": "system", "content": system},
        {"role": "user",   "content": user_msg},
    ], max_tokens=150, label="/ask")

    print(f"📤 /ask response: {len(out)} chars")

    if out and len(out) > 5:
        return {"answer": out, "source": "phi3", "status": "ok"}

    print("⚠️  /ask: empty output")
    return {"answer": "", "source": "empty", "status": "ok"}


@app.post("/analyze")
def analyze(req: AskRequest):
    """
    Background enrichment endpoint.
    Reduced to max_new_tokens=200 (was 250) to release the GPU
    sooner so /ask calls don't wait as long.
    """
    out = run([
        {"role": "system", "content": (
            "You are a SOC analyst. Output ONLY valid JSON. No explanation."
        )},
        {"role": "user", "content": (
            f"Telemetry:\n{req.context[:400]}\n\nTask: {req.question}"
        )},
    ], max_tokens=200, label="/analyze")

    return {
        "answer": out,
        "source": "phi3"  if out else "error",
        "status": "ok"    if out else "error"
    }


@app.get("/health")
def health():
    return {
        "status": "running",
        "model":  BASE_MODEL,
        "device": "cuda" if torch.cuda.is_available() else "cpu",
        "ready":  _pipe is not None
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)