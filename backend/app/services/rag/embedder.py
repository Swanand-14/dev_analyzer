from typing import List, Optional
from sentence_transformers import SentenceTransformer

_model: Optional[SentenceTransformer] = None
 
MODEL_NAME = "jinaai/jina-embeddings-v2-base-code"
EMBEDDING_DIM = 768  # jina-v2-code output dimension

def get_embedding_model() -> SentenceTransformer:
    """
    Returns the shared embedding model instance.
    Downloads on first call (~550MB), cached locally after that.
    """
    global _model
    if _model is None:
        print(f"Loading embedding model '{MODEL_NAME}'...")
        _model = SentenceTransformer(MODEL_NAME,trust_remote_code=True)
    print("Embedding model ready.")
    return _model

def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embeds a list of text strings.
    Returns a list of float vectors, one per input text.
 
    Batches automatically — safe to call with 1 or 1000 texts.
    """
    model = get_embedding_model()
    embeddings = model.encode(
        texts,
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,  # cosine similarity works on normalized vectors
    )
    return embeddings.tolist()

def embed_query(query: str) -> List[float]:
    """
    Embeds a single natural-language query for retrieval.
    jina-v2-code uses instruction prefixes for asymmetric retrieval —
    query-side gets a different prefix than document-side for better accuracy.
    """
    model = get_embedding_model()
    # Instruction prefix tells the model this is a retrieval query, not a document
    prefixed = f"Represent this query for searching code: {query}"
    embedding = model.encode(
        prefixed,
        normalize_embeddings=True,
    )
    return embedding.tolist()