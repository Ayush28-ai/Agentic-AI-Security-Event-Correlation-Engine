from langchain.tools import tool
from orchestrator import process_log
import json


@tool
def correlation_tool(input: str):
    """
    Correlates logs using ML anomaly detection APIs and correlation engine.
    Expects a JSON string containing log_type and log data.
    Returns correlated anomaly information.
    """

    try:
        data = json.loads(input)

        log = data.get("log")
        log_type = data.get("log_type")

        result = process_log(log, log_type)

        return json.dumps(result, default=str)

    except Exception as e:
        return f"Correlation error: {str(e)}"