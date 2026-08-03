# Embedding rebuild and rollback

Create a checkpointed job per exact model ID, dimension and corpus release. Build `gemini-embedding-2` and `gemini-embedding-001` independently, verify counts/content hashes and model-specific indexes, then switch retrieval metadata atomically. Resume skips completed `(model_id, dimensions, content_hash)` items. Rollback selects the prior verified job/index metadata; never copy vectors between model spaces. When both APIs are unavailable, retain lexical search and hand off when citations are insufficient.
