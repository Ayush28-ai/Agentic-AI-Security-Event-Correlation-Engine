from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain.tools import tool


@tool
def incident_memory(query: str):
    """
    Searches past SOC incidents stored in FAISS vector database.
    Input: natural language query.
    Output: similar past incidents.
    """
    results = search_incidents(query)
    return [r.page_content for r in results]


@tool
def store_incident(summary: str):
    """
    Stores a resolved SOC incident into FAISS memory for future retrieval.
    """
    add_incident(summary)
    return "Incident stored successfully"
