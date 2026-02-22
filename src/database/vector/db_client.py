import os
import threading

import chromadb
from chromadb.config import Settings
from src.utils.logging_config import logger, get_trace_id


class VectorDBClient:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(VectorDBClient, cls).__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        
        self.trace_id = get_trace_id()
        self.persist_directory = os.getenv("VECTOR_DB_PATH", "./chroma_data")
        
        logger.info(f"Initializing ChromaDB client at {self.persist_directory}")
        
        try:
            self.client = chromadb.PersistentClient(path=self.persist_directory)
            logger.info("ChromaDB PersistentClient initialized successfully")
            self._initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize ChromaDB: {str(e)}")
            raise

    def get_collection(self, name: str):
        """Retrieves or creates a collection by name."""
        logger.info(f"Accessing collection: {name}")
        return self.client.get_or_create_collection(name=name)

    def upsert(self, collection_name: str, ids: list, embeddings: list, metadatas: list):
        """Upserts vectors into a specified collection."""
        collection = self.get_collection(collection_name)
        logger.info(f"Upserting {len(ids)} vectors into {collection_name}")
        
        # Inject trace_id into metadata if not present
        for meta in metadatas:
            if "trace_id" not in meta:
                meta["trace_id"] = get_trace_id()
        
        collection.upsert(
            ids=ids,
            embeddings=embeddings,
            metadatas=metadatas
        )
        logger.info(f"Successfully upserted vectors into {collection_name}")

    def query(self, collection_name: str, query_embeddings: list, n_results: int = 5):
        """Queries the specified collection."""
        collection = self.get_collection(collection_name)
        logger.info(f"Querying {collection_name} for {n_results} results")
        
        results = collection.query(
            query_embeddings=query_embeddings,
            n_results=n_results
        )
        return results

if __name__ == "__main__":
    # Internal test
    from src.utils.logging_config import setup_logging
    setup_logging()
    
    db = VectorDBClient()
    col = db.get_collection("test_persistence")
    db.upsert("test_persistence", ["id1"], [[0.1, 0.2, 0.3]], [{"test": "value"}])
    res = db.query("test_persistence", [[0.1, 0.2, 0.3]], n_results=1)
    print(res)
