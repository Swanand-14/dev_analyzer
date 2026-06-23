# app/services/rag/__init__.py

from app.services.rag.client import (
    get_chroma_client,
    get_or_create_repo_collection,
    delete_repo_collection,
    repo_collection_exists,
    list_repo_collections,
)
from app.services.rag.embedder import (
    get_embedding_model,
    embed_texts,
    embed_query,
    EMBEDDING_DIM,
)

__all__ = [
    # client
    "get_chroma_client",
    "get_or_create_repo_collection",
    "delete_repo_collection",
    "repo_collection_exists",
    "list_repo_collections",
    # embedder
    "get_embedding_model",
    "embed_texts",
    "embed_query",
    "EMBEDDING_DIM",
]