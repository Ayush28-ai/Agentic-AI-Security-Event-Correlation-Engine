from fastapi import FastAPI
from pydantic import BaseModel
import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timezone

# ✅ Correct filenames matching your Jupyter files
model  = joblib.load("security_iforest.pkl")
scaler = joblib.load("anomaly_scaler.pkl")

FEATURES = [
    "Total Length of Fwd Packets",
    "Flow Packets/s",
    "Flow Duration",
    "Destination Port",
    "Total Fwd Packets",
    "SYN Flag Count"
]

app = FastAPI(title="Security Anomaly Detection API")


class NetworkFlow(BaseModel):
    bytes_per_flow:      float
    packets_per_second:  float
    flow_duration:       float
    destination_port:    int
    total_fwd_packets:   int
    syn_flag_count:      int


@app.post("/detect")
def detect_anomaly(flow: NetworkFlow):
    df = pd.DataFrame([{
        "Total Length of Fwd Packets": flow.bytes_per_flow,
        "Flow Packets/s":              flow.packets_per_second,
        "Flow Duration":               flow.flow_duration,
        "Destination Port":            flow.destination_port,
        "Total Fwd Packets":           flow.total_fwd_packets,
        "SYN Flag Count":              flow.syn_flag_count
    }])

    raw_score     = -model.score_samples(df[FEATURES])[0]
    anomaly_score = scaler.transform([[raw_score]])[0][0]

    if anomaly_score >= 0.7:
        signal = "unusual_traffic_pattern"
    elif anomaly_score >= 0.35:
        signal = "slightly_unusual"
    else:
        signal = "normal_traffic"

    return {
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "source":        "security",
        "entity":        str(flow.destination_port),
        "anomaly_score": round(float(anomaly_score), 2),
        "signal":        signal
    }


@app.get("/health")
def health():
    return {"status": "running", "service": "sec-api"}