from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

EMBED_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

def load_rag_store():
    try:
        return FAISS.load_local("soc_rag_db", embeddings)
    except:
        return FAISS.from_texts([], embeddings)

def add_incident(text):
    db = load_rag_store()
    db.add_texts([text])
    db.save_local("soc_rag_db")

def search_incidents(query, k=3):
    db = load_rag_store()
    return db.similarity_search(query, k=k)
