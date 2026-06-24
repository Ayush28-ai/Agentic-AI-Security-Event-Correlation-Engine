import json
from orchestrator import process_log
from llm_agent import analyze_with_llm


# -------------------------------
# INPUT LOG
# -------------------------------

query = {
    "log_type": "both",
    "log": {
        "ops": {
            "host": "server-12",
            "cpu": 95,
            "memory": 90
        },
        "security": {
            "bytes_per_flow": 1500,
            "packets_per_second": 350,
            "flow_duration": 800,
            "destination_port": 443,
            "total_fwd_packets": 35,
            "syn_flag_count": 12,
            "host": "server-12"   # IMPORTANT
        }
    }
}


# -------------------------------
# STEP 1: CORRELATION
# -------------------------------

correlated = process_log(query["log"], query["log_type"])

print("\n🔍 CORRELATED OUTPUT:\n")
print(json.dumps(correlated, indent=2, default=str))


# -------------------------------
# STEP 2: AI ANALYSIS
# -------------------------------

print("\n🎩 FINAL SOC DECISION:\n")

result = analyze_with_llm(correlated)

print(result)