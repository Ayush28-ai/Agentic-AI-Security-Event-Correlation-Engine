import os
import requests
from dotenv import load_dotenv

load_dotenv()

OPS_API_URL = os.getenv("OPS_API_URL", "http://host.docker.internal:5001/detect")
SEC_API_URL = os.getenv("SEC_API_URL", "http://host.docker.internal:5002/detect")

OPS_API_KEY = os.getenv("OPS_API_KEY", "")
SEC_API_KEY = os.getenv("SEC_API_KEY", "")

def call_ops_ml_api(features):
    try:
        headers  = {"Authorization": f"Bearer {OPS_API_KEY}",
                    "Content-Type": "application/json"}
        response = requests.post(OPS_API_URL,
                                 json={"features": features},
                                 headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️  OPS ML API unavailable ({e}) — using heuristic fallback")
        cpu = features.get("cpu", 0)
        return {
            "entity":        features.get("host", "unknown"),
            "anomaly_score": round(min(cpu / 100.0, 1.0), 2),
            "signal":        "high_cpu" if cpu > 80 else "normal",
            "timestamp":     None
        }

def call_security_ml_api(flow):
    try:
        headers  = {"Authorization": f"Bearer {SEC_API_KEY}",
                    "Content-Type": "application/json"}
        response = requests.post(SEC_API_URL,
                                 json=flow,
                                 headers=headers, timeout=5)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"⚠️  SEC ML API unavailable ({e}) — using heuristic fallback")
        syn   = flow.get("syn_flag_count", 0)
        pps   = flow.get("packets_per_second", 0)
        score = round(min((syn / 20.0 + pps / 1000.0) / 2, 1.0), 2)
        return {
            "entity":        flow.get("host", "unknown"),
            "anomaly_score": score,
            "signal":        "suspicious" if score > 0.5 else "normal",
            "timestamp":     None
        }