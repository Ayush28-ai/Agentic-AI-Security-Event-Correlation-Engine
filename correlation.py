from datetime import datetime, timedelta, timezone

EVENT_STORE = []
WINDOW = timedelta(minutes=5)

# ✅ Must be defined BEFORE normalize_security uses it
TOPOLOGY_MAP = {
    "443": "server-12",
    "80": "server-12",
    "22": "jump-box-01"
}

def store_event(event):
    EVENT_STORE.append(event)

def get_recent_events():
    now = datetime.now(timezone.utc)
    return [e for e in EVENT_STORE if now - e["timestamp"] <= WINDOW]

def normalize_ops(raw):
    timestamp = raw.get("timestamp")
    if timestamp:
        dt = datetime.fromisoformat(timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)
    return {
        "timestamp": dt,
        "source": "ops",
        "entity": raw.get("entity", "unknown"),
        "anomaly_score": raw.get("anomaly_score", 0),
        "signal": raw.get("signal", "ops_anomaly")
    }

def normalize_security(raw):
    timestamp = raw.get("timestamp")
    if timestamp:
        dt = datetime.fromisoformat(timestamp)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = datetime.now(timezone.utc)

    raw_entity = str(raw.get("entity", "unknown"))
    resolved_entity = TOPOLOGY_MAP.get(raw_entity, raw_entity)  # ✅ Now safe

    return {
        "timestamp": dt,
        "source": "security",
        "entity": resolved_entity,
        "anomaly_score": raw.get("anomaly_score", 0),
        "signal": raw.get("signal", "security_anomaly")
    }

def correlate_events(events):
    entity_map = {}
    for event in events:
        entity_map.setdefault(event["entity"], []).append(event)

    correlated_output = []
    for resolved_host, evs in entity_map.items():
        ops_events = [e for e in evs if e["source"] == "ops"]
        sec_events = [e for e in evs if e["source"] == "security"]
        correlated_output.append({
            "entity": resolved_host,
            "is_correlated": len(ops_events) > 0 and len(sec_events) > 0,
            "max_ops_score": max([e["anomaly_score"] for e in ops_events], default=0),
            "max_security_score": max([e["anomaly_score"] for e in sec_events], default=0),
            "ops_events": ops_events,
            "security_events": sec_events
        })
    return correlated_output

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
        "generated_at": datetime.now(timezone.utc).isoformat()
    }