from llm_agent import agent
import json

query = json.dumps({
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
            "syn_flag_count": 12
        }
    }
})

response = agent.run(query)

print("\nFINAL SOC DECISION:\n")
print(response)
