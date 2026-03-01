import os
import requests
from dotenv import load_dotenv

load_dotenv()

OPS_API_URL = "http://localhost:8001/detect"
SEC_API_URL = "http://localhost:8002/detect"

OPS_API_KEY = os.getenv("OPS_API_KEY")
SEC_API_KEY = os.getenv("SEC_API_KEY")
def call_ops_ml_api(features):
    headers = {
        "Authorization": f"Bearer {OPS_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {"features": features}
    response = requests.post(OPS_API_URL, json=payload, headers=headers)
    return response.json()



def call_security_ml_api(flow):
    headers = {
        "Authorization": f"Bearer {SEC_API_KEY}",
        "Content-Type": "application/json"
    }
    response = requests.post(SEC_API_URL, json=flow, headers=headers)
    return response.json()
