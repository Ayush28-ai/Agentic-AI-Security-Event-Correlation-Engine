import json
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timezone
import asyncio
from concurrent.futures import ThreadPoolExecutor

from orchestrator import process_log
from llm_agent import analyze_with_llm
from database import (
    init_db, store_incident, get_latest,
    get_by_device, get_device_status, set_device_status
)

app = FastAPI(title="SOC Monitor API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

init_db()

# ── Two separate pools ─────────────────────────────────────
# ML pool  — fast tasks, 8 workers
# LLM pool — slow Phi-3 calls, 2 workers (avoids GPU contention)
_ml_executor  = ThreadPoolExecutor(max_workers=8,
                                   thread_name_prefix="ml")
_llm_executor = ThreadPoolExecutor(max_workers=1,
                                   thread_name_prefix="llm")


# ── Request models ─────────────────────────────────────────
class MetricsPayload(BaseModel):
    device_name: str
    timestamp:   str
    ops:         dict
    security:    dict

class AlertPayload(BaseModel):
    device_name: str
    reason:      str
    severity:    str = "HIGH"

class ControlPayload(BaseModel):
    device_name: str
    action:      str

class AskPayload(BaseModel):
    question: str
    context:  str = ""
    mode:     str = "analyst"


# ── Deterministic helpers (no LLM, no I/O) ────────────────
def _quick_risk(entities):
    """Instant risk from ML scores — no LLM needed."""
    if not entities:
        return "LOW", "No anomalies detected in current window", "HIGH", "unknown"
    e      = entities[0]
    score  = round(e["max_ops_score"] + e["max_security_score"], 2)
    entity = e.get("entity", "unknown")
    if   score > 1.5: risk = "CRITICAL"
    elif score > 1.0: risk = "HIGH"
    elif score > 0.5: risk = "MEDIUM"
    else:             risk = "LOW"
    return risk, f"Anomaly on {entity} (score {score})", "MEDIUM", entity


def _default_actions(risk: str, entity: str) -> list:
    return {
        "CRITICAL": [
            f"Immediately isolate {entity} from the network",
            "Trigger Incident Response playbook",
            "Capture memory dump and preserve forensic evidence",
            "Notify SOC Lead and CISO"
        ],
        "HIGH": [
            f"Block suspicious traffic to/from {entity}",
            "Rotate credentials and API keys on affected host",
            "Enable enhanced logging on firewall and IDS",
            "Schedule emergency patch review"
        ],
        "MEDIUM": [
            f"Monitor {entity} closely for the next 24 hours",
            "Review recent access logs for anomalies",
            "Verify firewall rules are up to date"
        ],
        "LOW": [
            "Continue standard monitoring",
            "Log event for trend analysis"
        ]
    }.get(risk, ["Continue monitoring"])


def _background_llm(correlated, device_name, timestamp, ops, risk):
    """
    Runs in _llm_executor (max 2 concurrent).
    Enriches the stored incident after Phi-3 analysis completes.
    Never blocks the FastAPI event loop.
    """
    try:
        analysis_str = analyze_with_llm(correlated)
        analysis     = json.loads(analysis_str)
        store_incident(
            device_name=device_name,
            timestamp=timestamp,
            risk_level=analysis.get("risk_level", risk),
            ops=ops,
            analysis=analysis
        )
        print(f"🧠 LLM enriched — {device_name} "
              f"→ {analysis.get('risk_level')}")
    except Exception as e:
        print(f"⚠️  LLM background error ({device_name}): {e}")


# ══════════════════════════════════════════════════════════
# INSTANT ENDPOINTS — synchronous, always <10ms
# These must NEVER be async-def or touch any LLM/ML code.
# ══════════════════════════════════════════════════════════

@app.get("/health")
def health():
    return {
        "status": "running",
        "time":   datetime.now(timezone.utc).isoformat()
    }

@app.get("/agent/status/{device_name}")
def agent_status(device_name: str):
    return get_device_status(device_name)

@app.post("/agent/control")
def agent_control(payload: ControlPayload):
    set_device_status(payload.device_name, payload.action)
    return {
        "status": "ok",
        "device": payload.device_name,
        "action": payload.action
    }

@app.get("/incidents")
def incidents():
    rows = get_latest(50)
    for r in rows:
        if isinstance(r.get("analysis"), str):
            try:    r["analysis"] = json.loads(r["analysis"])
            except: r["analysis"] = {}
    return rows

@app.get("/incidents/{device_name}")
def incidents_by_device(device_name: str):
    rows = get_by_device(device_name)
    for r in rows:
        if isinstance(r.get("analysis"), str):
            try:    r["analysis"] = json.loads(r["analysis"])
            except: r["analysis"] = {}
    return rows

@app.post("/alert")
def trigger_alert(payload: AlertPayload):
    analysis = {
        "risk_level":          payload.severity,
        "affected_entity":     payload.device_name,
        "summary":             f"Manual alert: {payload.reason}",
        "root_cause":          "Manually triggered by IT operator",
        "recommended_actions": [
            "Investigate immediately",
            "Check device logs"
        ],
        "where_to_fix": [f"Host: {payload.device_name}"],
        "confidence":   "HIGH"
    }
    store_incident(
        device_name=payload.device_name,
        timestamp=datetime.now(timezone.utc).isoformat(),
        risk_level=payload.severity,
        ops={"cpu": 0, "memory": 0, "disk": 0},
        analysis=analysis
    )
    return {"status": "ok"}


# ══════════════════════════════════════════════════════════
# /ingest — TWO-PHASE ASYNC PIPELINE
#
# Phase 1 (~1-2s)  : ML scoring → deterministic risk → respond
# Phase 2 (~30-60s): LLM enrichment in background (HIGH/CRITICAL)
#
# /health stays <10ms regardless of LLM load because:
#  - /health is sync (not async), never queued behind LLM work
#  - Gunicorn 4 workers means 3 other workers always free
#  - LLM pool limited to 2 concurrent threads
# ══════════════════════════════════════════════════════════

@app.post("/ingest")
async def ingest(payload: MetricsPayload):
    try:
        log  = {"ops": payload.ops, "security": payload.security}
        loop = asyncio.get_event_loop()

        # ── Phase 1: ML + correlation (non-blocking) ──────
        def run_fast():
            correlated = process_log(log, "both")
            entities   = correlated.get("correlated_entities", [])
            risk, summary, confidence, entity = _quick_risk(entities)
            fast_analysis = {
                "risk_level":      risk,
                "affected_entity": entity,
                "summary":         summary,
                "root_cause": (
                    "ML anomaly detection — LLM enrichment pending"
                    if risk in ("HIGH","CRITICAL")
                    else "ML anomaly detection"
                ),
                "recommended_actions": _default_actions(
                    risk, payload.device_name
                ),
                "where_to_fix": [f"Host: {payload.device_name}"],
                "confidence":   confidence
            }
            return correlated, fast_analysis

        correlated, fast_analysis = await loop.run_in_executor(
            _ml_executor, run_fast
        )
        risk = fast_analysis["risk_level"]

        # Store fast result immediately — dashboard never waits
        store_incident(
            device_name=payload.device_name,
            timestamp=payload.timestamp,
            risk_level=risk,
            ops=payload.ops,
            analysis=fast_analysis
        )

        print(f"⚡ {payload.device_name} | "
              f"CPU:{payload.ops.get('cpu')}% | "
              f"Risk:{risk}")

        # ── Phase 2: LLM enrichment (background, limited pool) ─
        if risk in ("HIGH","CRITICAL"):
            loop.run_in_executor(
                _llm_executor,
                _background_llm,
                correlated,
                payload.device_name,
                payload.timestamp,
                payload.ops,
                risk
            )

        return {
            "status":     "ok",
            "risk_level": risk,
            "summary":    fast_analysis["summary"],
            "enriching":  risk in ("HIGH","CRITICAL")
        }

    except Exception as e:
        print(f"❌ Ingest error: {e}")
        return {"status": "error", "message": str(e)}


# ── /ask — proxy to host LLM service ──────────────────────
@app.post("/ask")
async def ask_analyst(payload: AskPayload):
    import requests as req_lib
    LLM_SERVICE = os.getenv(
        "LLM_SERVICE_URL", "http://host.docker.internal:8080"
    )

    def call():
        try:
            r = req_lib.post(
                f"{LLM_SERVICE}/ask",
                json={
                    "question": payload.question,
                    "context":  payload.context,
                    "mode":     payload.mode
                },
                timeout=90
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"⚠️  /ask proxy failed: {e}")
        return {"answer": "", "source": "error"}

    loop   = asyncio.get_event_loop()
    result = await loop.run_in_executor(_ml_executor, call)
    return result


# ── /pipeline/trace — debug endpoint ──────────────────────
@app.get("/pipeline/trace/{device_name}")
async def get_pipeline_trace(device_name: str):
    rows = get_by_device(device_name)          # no limit kwarg needed
    if not rows:
        return {"error": "No incidents found for this device"}
    row = rows[0]
    if isinstance(row.get("analysis"), str):
        try:    row["analysis"] = json.loads(row["analysis"])
        except: pass
    return row