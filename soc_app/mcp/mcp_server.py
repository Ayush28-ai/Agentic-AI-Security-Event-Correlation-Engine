import json
import sqlite3
import os
import asyncio
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from fastapi.responses import JSONResponse

app = FastAPI(title="SOC MCP Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"],
                   allow_methods=["*"], allow_headers=["*"])

DB_PATH    = os.getenv("DB_PATH", "/app/shared/soc_incidents.db")
SOC_SERVER = os.getenv("SERVER_URL", "http://soc-server:8000")

MCP_TOOLS = [
    {
        "name": "query_incidents",
        "description": "Query SOC incident database. Filter by device or risk level.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "device_name": {"type": "string"},
                "risk_level":  {"type": "string"},
                "limit":       {"type": "integer"}
            }
        }
    },
    {
        "name": "trigger_alert",
        "description": "Manually trigger a security alert for a device.",
        "inputSchema": {
            "type": "object",
            "required": ["device_name", "reason"],
            "properties": {
                "device_name": {"type": "string"},
                "reason":      {"type": "string"},
                "severity":    {"type": "string"}
            }
        }
    },
    {
        "name": "search_threat_intel",
        "description": "Search real-time threat intelligence for a CVE or attack pattern.",
        "inputSchema": {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"}
            }
        }
    },
    {
        "name": "control_agent",
        "description": "Start, stop, or pause monitoring for a device.",
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action":      {"type": "string"},
                "device_name": {"type": "string"}
            }
        }
    }
]


def tool_query_incidents(args):
    device = args.get("device_name")
    risk   = args.get("risk_level")
    limit  = args.get("limit", 10)

    if not os.path.exists(DB_PATH):
        return "Database not yet initialised — no incidents recorded."

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    query  = "SELECT * FROM incidents WHERE 1=1"
    params = []
    if device:
        query += " AND device_name LIKE ?"
        params.append(f"%{device}%")
    if risk:
        query += " AND risk_level = ?"
        params.append(risk.upper())
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    raw_rows = conn.execute(query, params).fetchall()
    conn.close()

    if not raw_rows:
        return "No incidents found."

    # ✅ Fixed — simple loop, no broken comprehension
    rows = [dict(r) for r in raw_rows]

    lines = [f"Found {len(rows)} incident(s):\n"]
    for r in rows:
        try:
            a = json.loads(r.get("analysis", "{}"))
        except:
            a = {}
        lines.append(
            f"• [{r['risk_level']}] {r['device_name']} at {r['timestamp'][:19]}\n"
            f"  {a.get('summary', 'N/A')}\n"
        )
    return "\n".join(lines)


def tool_trigger_alert(args):
    import requests
    try:
        r = requests.post(f"{SOC_SERVER}/alert", json={
            "device_name": args.get("device_name"),
            "reason":      args.get("reason"),
            "severity":    args.get("severity", "HIGH")
        }, timeout=5)
        return f"Alert triggered: {r.json()}"
    except Exception as e:
        return f"Alert failed: {e}"


def tool_search_threat_intel(args):
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(args.get("query", ""), max_results=3))
        if not results:
            return "No results found."
        lines = []
        for r in results:
            lines.append(
                f"• {r.get('title', '')}\n"
                f"  {r.get('body', '')[:200]}\n"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Search failed: {e}"


def tool_control_agent(args):
    import requests
    action = args.get("action", "status").lower()
    device = args.get("device_name")

    if action == "status":
        try:
            if device:
                r = requests.get(
                    f"{SOC_SERVER}/agent/status/{device}", timeout=5
                )
                return f"Status for {device}: {r.json().get('status', 'unknown')}"
            return "Specify a device_name to check status."
        except Exception as e:
            return f"Status check failed: {e}"

    try:
        r = requests.post(f"{SOC_SERVER}/agent/control", json={
            "device_name": device or "all",
            "action":      action
        }, timeout=5)
        return f"Agent control result: {r.json()}"
    except Exception as e:
        return f"Control failed: {e}"


TOOL_MAP = {
    "query_incidents":     tool_query_incidents,
    "trigger_alert":       tool_trigger_alert,
    "search_threat_intel": tool_search_threat_intel,
    "control_agent":       tool_control_agent
}


@app.get("/sse")
async def sse_endpoint():
    async def generator():
        yield {
            "event": "message",
            "data": json.dumps({"type": "tools/list", "tools": MCP_TOOLS})
        }
        while True:
            await asyncio.sleep(15)
            yield {"event": "ping", "data": "{}"}
    return EventSourceResponse(generator())


@app.post("/call")
async def call_tool(body: dict):
    name = body.get("name")
    args = body.get("arguments", {})
    print(f"MCP tool: {name} | {args}")
    if name not in TOOL_MAP:
        return JSONResponse({"error": f"Unknown tool: {name}"}, status_code=404)
    try:
        result = TOOL_MAP[name](args)
        return {"content": [{"type": "text", "text": result}]}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/health")
def health():
    return {"status": "running", "tools": len(MCP_TOOLS)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)