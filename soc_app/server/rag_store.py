import os
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
RAG_DB_PATH = os.getenv("RAG_DB_PATH", "/app/data/soc_rag_db")

# ✅ Single shared embeddings instance — avoid reloading every call
embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)


def load_rag_store():
    """Load existing FAISS store or create a new empty one."""
    try:
        if os.path.exists(RAG_DB_PATH):
            return FAISS.load_local(
                RAG_DB_PATH,
                embeddings,
                allow_dangerous_deserialization=True  # ✅ required in newer langchain
            )
    except Exception as e:
        print(f"⚠️  RAG load error: {e}")

    # ✅ Create with a dummy text so FAISS index is initialized
    # (FAISS cannot create a valid index from empty list)
    db = FAISS.from_texts(["SOC system initialized."], embeddings)
    db.save_local(RAG_DB_PATH)
    return db


def add_incident(text: str):
    """Add a new incident to the FAISS store and persist it."""
    try:
        db = load_rag_store()
        db.add_texts([text])
        db.save_local(RAG_DB_PATH)
        print(f"✅ RAG: stored incident ({len(text)} chars)")
    except Exception as e:
        print(f"⚠️  RAG add_incident failed: {e}")


def search_incidents(query: str, k: int = 3):
    """Search for similar past incidents."""
    try:
        db = load_rag_store()

        # ✅ Skip search if only the init placeholder exists
        if db.index.ntotal <= 1:
            return []

        results = db.similarity_search(query, k=k)
        return results if results else []

    except Exception as e:
        print(f"⚠️  RAG search failed: {e}")
        return []