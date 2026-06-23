import re
import chromadb
from chromadb.config import Settings
from typing import Optional

_client: Optional[chromadb.ClientAPI] = None

def get_chroma_client() -> chromadb.ClientAPI:
    """
    Returns the shared ChromaDB client.
    Initializes once and reuses across the app lifetime.
 
   
    """
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path="./chroma_store",
            settings=Settings(anonymized_telemetry=False),
        )
    return _client

def _repo_url_to_collection_name(repo_url:str) -> str:
    """
    Rules:
      - Chroma collection names: 3-63 chars, alphanumeric + underscores/hyphens
      - We prefix with "repo_" to namespace away from any future collections
      - All non-alphanumeric chars (/, ., -, etc.) become underscores
 
    Examples:
      "Swanand-14/testrepo"                    → "repo_swanand_14_testrepo"
      "https://github.com/Swanand-14/testrepo" → "repo_swanand_14_testrepo"
    """
    url = repo_url.lower()
    if "github.com" in url:
        parts = url.rstrip("/").split("/")
        url = f"{parts[-2]}/{parts[-1]}"
 
    # Replace all non-alphanumeric chars with underscores
    slug = re.sub(r"[^a-z0-9]+", "_", url).strip("_")
 
    # Prefix + truncate to 63 chars (Chroma limit)
    name = f"repo_{slug}"[:63]
    return name

def get_or_create_repo_collection(repo_url: str) -> chromadb.Collection:
    """
    Gets or creates the Chroma collection for a specific repo.
    Uses cosine distance — appropriate for normalized embedding vectors.
    """
    client = get_chroma_client()
    name   = _repo_url_to_collection_name(repo_url)
 
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine", "repo_url": repo_url},
    )

def delete_repo_collection(repo_url: str) -> bool:
    """
    Deletes a repo's collection entirely.
    Called before re-ingestion so we get a clean slate (no stale chunks).
    Returns True if deleted, False if didn't exist.
    """
    client = get_chroma_client()
    name = _repo_url_to_collection_name(repo_url)
    try:
        client.delete_collection(name)
        print(f"Deleted Chroma collection '{name}' for repo '{repo_url}'")
        return True
    except Exception as e:
        print(f"Collection '{name}' for repo '{repo_url}' did not exist or couldn't be deleted: {e}")
        return False
    
def repo_collection_exists(repo_url: str) -> bool:
    """Returns True if a collection exists for this repo."""
    client = get_chroma_client()
    name   = _repo_url_to_collection_name(repo_url)
    try:
        client.get_collection(name)
        return True
    except Exception:
        return False
    

    
def list_repo_collections() -> list:
    """Lists all repo collections currently stored."""
    client = get_chroma_client()
    return [c.name for c in client.list_collections() if c.name.startswith("repo_")]

    
