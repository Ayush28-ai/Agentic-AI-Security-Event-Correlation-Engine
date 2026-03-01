from datetime import datetime, timedelta , timezone

# -------------------------
# Event Store
# -------------------------

EVENT_STORE = []
WINDOW = timedelta(minutes=5)


# -------------------------
# Store event
# -------------------------

def store_event(event):
    EVENT_STORE.append(event)


# -------------------------
# Get recent events
# -------------------------

def get_recent_events():
    now = datetime.now(timezone.utc)
    return [
        e for e in EVENT_STORE
        if now - e["timestamp"] <= WINDOW
    ]


# -------------------------
# Normalize ML outputs
# -------------------------

def normalize_ops(raw):
    return {
        "timestamp": datetime.fromisoformat(raw["timestamp"]),
        "source": "ops",
        "entity": raw["entity"],
        "anomaly_score": raw["anomaly_score"],
        "signal": raw.get("signal", "ops_anomaly")
    }


def normalize_security(raw):
    return {
        "timestamp": datetime.fromisoformat(raw["timestamp"]),
        "source": "security",
        "entity": raw["entity"],
        "anomaly_score": raw["anomaly_score"],
        "signal": raw.get("signal", "security_anomaly")
    }


# -------------------------
# Correlation Logic
# -------------------------

def correlate_events(events):

    entity_map = {}

    for event in events:
        entity_map.setdefault(event["entity"], []).append(event)

    correlated_output = []

    for entity, evs in entity_map.items():

        ops_events = [e for e in evs if e["source"] == "ops"]
        sec_events = [e for e in evs if e["source"] == "security"]

        correlated_output.append({

            "entity": entity,

            "time_window_minutes": WINDOW.seconds // 60,

            "ops_events_count": len(ops_events),

            "security_events_count": len(sec_events),

            "max_ops_score": max(
                [e["anomaly_score"] for e in ops_events],
                default=0
            ),

            "max_security_score": max(
                [e["anomaly_score"] for e in sec_events],
                default=0
            ),

            "ops_events": ops_events,

            "security_events": sec_events

        })

    return correlated_output


# -------------------------
# Main Pipeline
# -------------------------

def correlation_pipeline(raw_ops=None, raw_security=None):

    if raw_ops:
        store_event(normalize_ops(raw_ops))

    if raw_security:
        store_event(normalize_security(raw_security))

    recent_events = get_recent_events()

    correlated_data = correlate_events(recent_events)

    return {
        "correlated_entities": correlated_data,
        "total_entities_affected": len(correlated_data),
        "generated_at": datetime.utcnow().isoformat()
    }
