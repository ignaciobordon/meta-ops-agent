import os
import shutil
from src.database.vector.db_client import VectorDBClient
from src.utils.logging_config import setup_logging, set_trace_id, logger

def test_persistence():
    setup_logging()
    trace_id = set_trace_id("cp0-persistence-test")
    logger.info(f"Starting CP0 Persistence Test. TraceID: {trace_id}")
    
    # Ensure a clean state for the test directory if needed, 
    # but for true persistence test we want to write and then re-read.
    persist_dir = "./chroma_data_test"
    os.environ["VECTOR_DB_PATH"] = persist_dir
    
    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir)

    # 1. First initialization and write
    logger.info("Step 1: Initializing client and writing data")
    db1 = VectorDBClient()
    collection_name = "persistence_check"
    test_id = "vec_001"
    test_vec = [0.1, 0.2, 0.3, 0.4]
    test_meta = {"name": "test_object", "version": "v1"}
    
    db1.upsert(collection_name, [test_id], [test_vec], [test_meta])
    logger.info("Data written successfully")
    
    # Force delete the client instance to simulate "restart"
    VectorDBClient._instance = None
    
    # 2. Second initialization and read
    logger.info("Step 2: Re-initializing client and reading data")
    db2 = VectorDBClient()
    results = db2.query(collection_name, [test_vec], n_results=1)
    
    # Validation
    if results and results['ids'] and results['ids'][0][0] == test_id:
        logger.info("SUCCESS: Data retrieved correctly after re-initialization")
        # Check trace_id in metadata
        retrieved_meta = results['metadatas'][0][0]
        if retrieved_meta.get("trace_id") == trace_id:
            logger.info("SUCCESS: Trace ID propagated correctly in metadata")
        else:
            logger.warning(f"Trace ID mismatch or missing in metadata: {retrieved_meta.get('trace_id')}")
        return True
    else:
        logger.error("FAILURE: Data not found or mismatch after re-initialization")
        return False

if __name__ == "__main__":
    success = test_persistence()
    if success:
        print("\n[PASS] CP0: Vector Layer Persistence Test Successful")
        exit(0)
    else:
        print("\n[FAIL] CP0: Vector Layer Persistence Test Failed")
        exit(1)
