import json
import re
import os
import torch
from langchain_community.llms import HuggingFacePipeline
from transformers import (
    AutoTokenizer,
    AutoModelForCausalLM,
    BitsAndBytesConfig,
    pipeline
)
from peft import PeftModel

# Tools
from tools.search_tool import search_tool
from tools.rag_tool import incident_memory, store_incident

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

# -------------------------------
# LOAD PHI-3 + LORA ADAPTERS
# -------------------------------
BASE_MODEL = "microsoft/Phi-3-mini-4k-instruct"
LORA_MODEL = "./soc_llm_phi3"

bnb_config = BitsAndBytesConfig(
    load_in_8bit=True,
    llm_int8_threshold=6.0,
    llm_int8_has_fp16_weight=False
)

tokenizer = AutoTokenizer.from_pretrained(
    LORA_MODEL,
    trust_remote_code=True
)
tokenizer.pad_token = tokenizer.eos_token

base_model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    quantization_config=bnb_config,
    trust_remote_code=True,
    attn_implementation="eager",
    use_cache=True
)

# Load LoRA adapters
peft_model = PeftModel.from_pretrained(base_model, LORA_MODEL)
peft_model.eval()

# ✅ KEY FIX: merge LoRA weights into base model so pipeline() sees
# a standard Phi3ForCausalLM instead of unsupported PeftModelForCausalLM
merged_model = peft_model.merge_and_unload()
merged_model.eval()

hf_pipeline = pipeline(
    "text-generation",
    model=merged_model,             # ✅ merged model, not peft_model
    tokenizer=tokenizer,
    max_new_tokens=256,
    do_sample=False,
    return_full_text=False,
    trust_remote_code=True
)

llm = HuggingFacePipeline(pipeline=hf_pipeline)


# -------------------------------
# RISK SCORING
# -------------------------------
def compute_risk(e):
    score = e["max_ops_score"] + e["max_security_score"]
    if score > 1.5:
        return "CRITICAL"
    elif score > 1.0:
        return "HIGH"
    elif score > 0.5:
        return "MEDIUM"
    return "LOW"


# -------------------------------
# PLACEHOLDER DETECTOR
# -------------------------------
PLACEHOLDER_MARKERS = [
    "what is happening", "why it is happening",
    "action1", "action2", "location1",
    "technical action", "technical summary",
    "hypothesis based", "host/service",
    "describe the anomaly", "explain the likely",
    "first remediation", "second remediation",
    "affected system or service",
    "one sentence describing",
    "one sentence explaining"
]

def is_placeholder(value):
    if not value:
        return True
    if isinstance(value, list):
        return all(is_placeholder(v) for v in value)
    text = str(value).lower()
    return any(marker in text for marker in PLACEHOLDER_MARKERS)


# -------------------------------
# JSON EXTRACTOR
# -------------------------------
def extract_json(text):
    if not text or not text.strip():
        return None

    # Strategy 1: Direct parse
    try:
        return json.loads(text.strip())
    except:
        pass

    # Strategy 2: Strip markdown fences
    cleaned = re.sub(r'```json|```', '', text).strip()
    try:
        return json.loads(cleaned)
    except:
        pass

    # Strategy 3: Greedy {...} block — captures full nested JSON
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except:
            pass

    # Strategy 4: Largest non-nested {...} block
    matches = re.findall(r'\{[^{}]*\}', cleaned, re.DOTALL)
    for m in sorted(matches, key=len, reverse=True):
        try:
            return json.loads(m)
        except:
            continue

    # Strategy 5: Model dropped outer braces
    if not cleaned.startswith('{'):
        try:
            wrapped = '{' + cleaned.rstrip(',') + '}'
            return json.loads(wrapped)
        except:
            pass

    return None


# -------------------------------
# BUILD FALLBACK
# -------------------------------
def build_fallback(priority, threat, memory):
    risk     = priority["risk"]
    entity   = priority["entity"]
    combined = round(priority["ops_score"] + priority["security_score"], 3)

    actions_map = {
        "CRITICAL": [
            f"Immediately isolate {entity} from the network",
            "Trigger IR (Incident Response) playbook",
            "Capture memory dump and preserve forensic evidence",
            "Notify SOC Lead and CISO"
        ],
        "HIGH": [
            f"Block all suspicious traffic to/from {entity}",
            "Rotate credentials and API keys on affected host",
            "Enable enhanced logging on firewall and IDS",
            "Schedule emergency patch review"
        ],
        "MEDIUM": [
            f"Monitor {entity} closely for next 24 hours",
            "Review recent access logs for anomalies",
            "Verify firewall rules are up to date"
        ],
        "LOW": [
            "Continue standard monitoring",
            "Log event for trend analysis"
        ]
    }

    threat_snippet = (
        threat[:150]
        if threat and "unreachable" not in threat and len(threat) > 20
        else "No external intel available"
    )
    memory_snippet = (
        str(memory)[:100]
        if memory and "No historical" not in str(memory)
        else "No prior incidents on record"
    )

    return {
        "risk_level": risk,
        "affected_entity": entity,
        "summary": (
            f"Entity {entity} shows combined anomaly score of {combined}. "
            f"Ops: {priority['ops_score']}, Security: {priority['security_score']}. "
            f"Threat context: {threat_snippet}"
        ),
        "root_cause": (
            f"Correlated ops and security anomalies on {entity}. "
            f"Historical context: {memory_snippet}"
        ),
        "recommended_actions": actions_map.get(risk, actions_map["MEDIUM"]),
        "where_to_fix": [
            f"Host: {entity}",
            "Network: Firewall and IDS rules",
            "Application: Service logs and configs"
        ],
        "confidence": "HIGH" if combined > 1.0 else "MEDIUM"
    }


# -------------------------------
# MAIN ANALYZER
# -------------------------------
def analyze_with_llm(correlated_data):

    entities = correlated_data.get("correlated_entities", [])

    if not entities:
        return json.dumps({
            "risk_level": "LOW",
            "summary": "No anomalies detected in current time window",
            "confidence": "HIGH"
        }, indent=2)

    # 1️⃣ ENRICH
    enriched = []
    for e in entities:
        enriched.append({
            "entity": e["entity"],
            "ops_score": e["max_ops_score"],
            "security_score": e["max_security_score"],
            "risk": compute_risk(e)
        })

    # 2️⃣ PRIORITY ENTITY
    risk_order = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
    priority = sorted(
        enriched,
        key=lambda x: (risk_order.get(x["risk"], 0),
                       x["ops_score"] + x["security_score"]),
        reverse=True
    )[0]

    print(f"\n🎯 PRIORITY ENTITY: {priority['entity']} | "
          f"Risk: {priority['risk']} | "
          f"Score: {round(priority['ops_score'] + priority['security_score'], 3)}")

    # 3️⃣ RAG MEMORY
    try:
        memory = incident_memory.run(f"Previous alerts for {priority['entity']}")
        print(f"\n📚 RAG MEMORY:\n{str(memory)[:300]}\n")
    except Exception as e:
        memory = "No historical data."
        print(f"⚠️  RAG lookup failed: {e}")

    # 4️⃣ THREAT INTEL
    if str(priority['entity']).isdigit():
        search_query = f"network port {priority['entity']} attack vulnerabilities CVE"
    else:
        search_query = f"server {priority['entity']} CVE exploits attack patterns"

    try:
        threat = search_tool.run(search_query)
        print(f"\n🌐 THREAT INTEL:\n{threat[:400]}\n")
        if not threat or "No good" in threat or len(threat) < 50:
            threat = search_tool.run(
                f"cybersecurity {priority['risk']} risk attack mitigation"
            )
    except Exception as e:
        threat = "External intelligence database unreachable."
        print(f"⚠️  Search failed: {e}")

    # 5️⃣ BUILD PROMPT — Phi-3 chat format
    fallback_for_prompt = build_fallback(priority, threat, memory)
    actions_json = json.dumps(fallback_for_prompt["recommended_actions"])
    where_json   = json.dumps(fallback_for_prompt["where_to_fix"])

    telemetry = " | ".join([
        f"{e['entity']}(ops={e['ops_score']},sec={e['security_score']},risk={e['risk']})"
        for e in enriched
    ])

    prompt = (
        f"<|system|>\n"
        f"You are a SOC AI Analyst. Output only valid JSON. No extra text.\n"
        f"<|end|>\n"
        f"<|user|>\n"
        f"Analyze this security telemetry and fill in summary and root_cause.\n\n"
        f"Telemetry: {telemetry}\n"
        f"ThreatIntel: {threat[:200]}\n"
        f"History: {str(memory)[:120]}\n\n"
        f"Return this exact JSON with real values for summary and root_cause:\n"
        f'{{"risk_level":"{priority["risk"]}",'
        f'"affected_entity":"{priority["entity"]}",'
        f'"summary":"one sentence describing what anomaly is occurring",'
        f'"root_cause":"one sentence explaining the likely technical cause",'
        f'"recommended_actions":{actions_json},'
        f'"where_to_fix":{where_json},'
        f'"confidence":"HIGH"}}\n'
        f"<|end|>\n"
        f"<|assistant|>\n"
    )

    print(f"\n📝 PROMPT:\n{prompt}\n")

    # 6️⃣ LLM INFERENCE
    try:
        response = llm.invoke(prompt)
        output = response.content if hasattr(response, "content") else str(response)
        # ✅ Strip any trailing Phi-3 end tokens from output
        output = output.replace("<|end|>", "").replace("<|endoftext|>", "").strip()
        print(f"\n🤖 PHI-3 OUTPUT:\n{output}\n")
    except Exception as e:
        print(f"⚠️  LLM inference failed: {e}")
        output = ""

    # 7️⃣ PARSE + PATCH
    parsed = extract_json(output)
    required_keys = ["risk_level", "affected_entity", "summary",
                     "root_cause", "recommended_actions",
                     "where_to_fix", "confidence"]

    if parsed:
        print("✅ Phi-3 JSON parsed successfully")
        fallback = build_fallback(priority, threat, memory)
        patched = []
        for key in required_keys:
            if key not in parsed or is_placeholder(parsed[key]):
                parsed[key] = fallback[key]
                patched.append(key)
        if patched:
            print(f"  🔧 Patched: {patched}")
    else:
        print("⚠️  Using enriched fallback")
        parsed = build_fallback(priority, threat, memory)

    # 8️⃣ STORE IN RAG
    try:
        store_incident.run(json.dumps(parsed))
        print("💾 Incident stored in RAG memory")
    except Exception as e:
        print(f"⚠️  Store failed: {e}")

    return json.dumps(parsed, indent=2)