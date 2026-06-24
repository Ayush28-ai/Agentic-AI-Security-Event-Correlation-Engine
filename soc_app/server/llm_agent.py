import json
import re
import os
import requests as http_requests

from tools.search_tool import search_tool
from tools.rag_tool import incident_memory, store_incident

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

LLM_SERVICE = os.getenv("LLM_SERVICE_URL", "http://host.docker.internal:8080")


# ── LLM calls ─────────────────────────────────────────────

def call_llm(prompt: str, max_tokens: int = 512,
             temperature: float = 0.3) -> str:
    """
    Call /generate on host LLM service.
    Timeout=45s so the background thread fails fast
    and the fallback analysis is returned instead of hanging.
    """
    try:
        r = http_requests.post(
            f"{LLM_SERVICE}/generate",
            json={"prompt": prompt,
                  "max_tokens": max_tokens,
                  "temperature": temperature},
            timeout=100
        )
        if r.status_code == 200:
            return r.json().get("output", "")
        return ""
    except Exception as e:
        print(f"⚠️  LLM /generate unavailable: {e}")
        return ""


def call_llm_analyze(context: str, task: str) -> str:
    """
    Call /analyze for structured JSON incident assessment.
    Timeout=45s — returns empty string on timeout so the
    deterministic fallback is used.
    """
    try:
        r = http_requests.post(
            f"{LLM_SERVICE}/analyze",
            json={"question": task, "context": context, "mode": "incident"},
            timeout=90
        )
        if r.status_code == 200:
            return r.json().get("answer", "")
        return ""
    except Exception as e:
        print(f"⚠️  LLM /analyze unavailable: {e}")
        return ""


# ── Risk scoring ──────────────────────────────────────────

def compute_risk(e):
    score = e["max_ops_score"] + e["max_security_score"]
    if   score > 1.5: return "CRITICAL"
    elif score > 1.0: return "HIGH"
    elif score > 0.5: return "MEDIUM"
    return "LOW"


# ── Placeholder detection ─────────────────────────────────

PLACEHOLDER_MARKERS = [
    "what is happening", "why it is happening",
    "action1", "action2", "location1",
    "technical action", "technical summary",
    "hypothesis based", "host/service",
    "describe the anomaly", "explain the likely",
    "one sentence describing", "one sentence explaining",
    "fill in", "your answer here"
]

def is_placeholder(value):
    if not value:
        return True
    if isinstance(value, list):
        return all(is_placeholder(v) for v in value)
    return any(m in str(value).lower() for m in PLACEHOLDER_MARKERS)


# ── JSON extraction ───────────────────────────────────────

def extract_json(text):
    if not text or not text.strip():
        return None
    try:
        return json.loads(text.strip())
    except: pass

    cleaned = re.sub(r'```json|```', '', text).strip()
    try:
        return json.loads(cleaned)
    except: pass

    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:   return json.loads(match.group(0))
        except: pass

    matches = re.findall(r'\{[^{}]*\}', cleaned, re.DOTALL)
    for m in sorted(matches, key=len, reverse=True):
        try:   return json.loads(m)
        except: continue

    if not cleaned.startswith('{'):
        try:   return json.loads('{' + cleaned.rstrip(',') + '}')
        except: pass

    return None


# ── Fallback builder ──────────────────────────────────────

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
        "risk_level":      risk,
        "affected_entity": entity,
        "summary": (
            f"Entity {entity} shows combined anomaly score of {combined}. "
            f"Ops: {priority['ops_score']}, "
            f"Security: {priority['security_score']}. "
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


# ── Main analyzer ─────────────────────────────────────────

def analyze_with_llm(correlated_data):
    """
    Full LLM-enriched analysis.
    Called from the background daemon thread in app.py
    so it never blocks the FastAPI event loop.
    """
    entities = correlated_data.get("correlated_entities", [])

    if not entities:
        return json.dumps({
            "risk_level": "LOW",
            "summary":    "No anomalies detected in current time window",
            "confidence": "HIGH"
        }, indent=2)

    # Enrich all entities
    enriched = []
    for e in entities:
        enriched.append({
            "entity":         e["entity"],
            "ops_score":      e["max_ops_score"],
            "security_score": e["max_security_score"],
            "risk":           compute_risk(e)
        })

    # Find highest priority
    risk_order = {"CRITICAL":4,"HIGH":3,"MEDIUM":2,"LOW":1}
    priority   = sorted(
        enriched,
        key=lambda x: (risk_order.get(x["risk"],0),
                       x["ops_score"] + x["security_score"]),
        reverse=True
    )[0]

    print(f"\n🎯 PRIORITY: {priority['entity']} | "
          f"Risk: {priority['risk']} | "
          f"Score: {round(priority['ops_score']+priority['security_score'],3)}")

    # RAG lookup
    try:
        memory = incident_memory.run(
            f"Previous alerts for {priority['entity']}"
        )
        print(f"\n📚 RAG:\n{str(memory)[:200]}\n")
    except Exception as e:
        memory = "No historical data."
        print(f"⚠️  RAG failed: {e}")

    # Threat intel
    search_query = (
        f"network port {priority['entity']} attack CVE vulnerabilities"
        if str(priority['entity']).isdigit()
        else f"{priority['entity']} server CVE exploits attack patterns 2025"
    )
    try:
        threat = search_tool.run(search_query)
        print(f"\n🌐 THREAT INTEL:\n{threat[:300]}\n")
        if not threat or len(threat) < 50:
            threat = search_tool.run(
                f"cybersecurity {priority['risk']} risk "
                f"attack mitigation best practices"
            )
    except Exception as e:
        threat = "External intelligence database unreachable."
        print(f"⚠️  Search failed: {e}")

    # Deterministic fallback (always used as base)
    parsed = build_fallback(priority, threat, memory)

    # Context for LLM
    telemetry = " | ".join([
        f"{e['entity']}(ops={e['ops_score']},"
        f"sec={e['security_score']},risk={e['risk']})"
        for e in enriched
    ])
    context = (
        f"Telemetry: {telemetry}\n"
        f"ThreatIntel: {threat[:300]}\n"
        f"History: {str(memory)[:150]}\n"
        f"Priority entity: {priority['entity']} risk={priority['risk']}"
    )
    task = (
        f"Analyze this security incident. "
        f"Fill in summary and root_cause fields in this JSON:\n"
        f'{{"risk_level":"{priority["risk"]}",'
        f'"affected_entity":"{priority["entity"]}",'
        f'"summary":"<one sentence: what anomaly is occurring>",'
        f'"root_cause":"<one sentence: technical cause>",'
        f'"recommended_actions":{json.dumps(parsed["recommended_actions"])},'
        f'"where_to_fix":{json.dumps(parsed["where_to_fix"])},'
        f'"confidence":"{parsed["confidence"]}"}}'
    )

    # LLM enhancement — only improves summary/root_cause fields
    output = call_llm_analyze(context, task)
    if output:
        llm_parsed = extract_json(output)
        if llm_parsed:
            for key in ["summary", "root_cause"]:
                val = llm_parsed.get(key, "")
                if val and not is_placeholder(val) and len(val) > 20:
                    parsed[key] = val
                    print(f"✅ LLM enhanced field: {key}")

    # Store in RAG memory
    try:
        store_incident.run(json.dumps(parsed))
        print("💾 Incident stored in RAG")
    except Exception as e:
        print(f"⚠️  RAG store failed: {e}")

    return json.dumps(parsed, indent=2)