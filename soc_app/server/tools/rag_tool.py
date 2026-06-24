from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.tools import tool
from rag_store import search_incidents, add_incident

@tool
def incident_memory(query: str):
    """
    Searches past SOC incidents stored in FAISS vector database.
    Input: natural language query.
    Output: similar past incidents as a string.
    """
    try:
        results = search_incidents(query)
        if not results:
            return "No historical data."
        # ✅ Safely convert list to string — never index directly
        return "\n".join([
            r.page_content if hasattr(r, "page_content") else str(r)
            for r in results
        ])
    except Exception as e:
        return f"No historical data. (RAG error: {str(e)})"


@tool
def store_incident(summary: str):
    """
    Stores a resolved SOC incident into FAISS memory for future retrieval.
    """
    try:
        add_incident(summary)
        return "Incident stored successfully"
    except Exception as e:
        return f"Storage failed: {str(e)}"