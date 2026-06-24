import os
import shutil
from rag_store import add_incident, search_incidents
from tools.rag_tool import incident_memory, store_incident


def run_verification():
    print("--- 🧪 STARTING RAG VERIFICATION ---")

    # 1. Clean start (optional): Delete old DB to ensure we aren't seeing old data
    db_path = "soc_rag_db"
    if os.path.exists(db_path):
        print("🗑️  Cleaning existing database for a fresh test...")
        shutil.rmtree(db_path)

    # 2. Test basic storage (rag_store.py)
    test_incident = "CRITICAL: server-12 experienced a brute force attack on SSH port 22 by IP 192.168.1.50."
    print("\n📦 Testing raw storage...")
    add_incident(test_incident)

    # 3. Test raw search (rag_store.py)
    print("\n🔍 Testing raw search (semantic similarity)...")
    # Query is similar but not identical
    results = search_incidents("SSH login attempts on server-12", k=1)

    if results and test_incident in results[0].page_content:
        print(f"✅ Raw Search Success: Found incident!")
    else:
        print("❌ Raw Search Failed: Could not find the incident.")

    # 4. Test Tool Integration (rag_tool.py)
    print("\n🛠️  Testing LangChain Tool wrappers...")

    # Test store_incident tool
    tool_input = "MEDIUM: Unauthorized access attempt detected on database-01."
    store_result = store_incident.invoke(tool_input)
    print(f"Result from store_incident tool: {store_result}")

    # Test incident_memory tool
    memory_output = incident_memory.invoke("Anything about database-01?")

    if "Unauthorized access" in memory_output:
        print("✅ Tool Search Success: Memory retrieved correctly.")
    else:
        print(f"❌ Tool Search Failed: Output was: {memory_output}")

    print("\n--- ✅ VERIFICATION COMPLETE ---")


if __name__ == "__main__":
    run_verification()