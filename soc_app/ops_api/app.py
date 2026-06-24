from fastapi import FastAPI
from pydantic import BaseModel
import joblib
import pandas as pd
import numpy as np
from datetime import datetime, timezone

model             = joblib.load("ops_anomaly_model.joblib")
expected_features = joblib.load("ops_features.joblib")

app = FastAPI(title="Ops Anomaly Detection Service")


class OpsInput(BaseModel):
    features: dict


@app.post("/detect")
def detect_ops_anomaly(data: OpsInput):
    X = pd.DataFrame(
        [[data.features.get(f, 0) for f in expected_features]],
        columns=expected_features
    )

    raw_score        = -model.decision_function(X)[0]
    anomaly          = model.predict(X)[0]
    normalized_score = 1 / (1 + np.exp(-raw_score))

    return {
        "timestamp":     datetime.now(timezone.utc).isoformat(),
        "source":        "ops",
        "entity":        data.features.get("host", "unknown"),
        "anomaly_score": round(float(normalized_score), 2),
        "signal":        "block_error_pattern" if anomaly == -1 else "normal"
    }


@app.get("/health")
def health():
    return {"status": "running", "service": "ops-api"}