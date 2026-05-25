import uuid
import logging
from services.coding.app.db import SessionLocal
from services.coding.app.main import run_coding
from services.coding.app.icd10_rag import _search_icd10_rag_cached, get_cache_stats

logging.basicConfig(level=logging.INFO)

async def test():
    claim_id = "82f6341d-8c41-406c-9243-f9d9d92a7aa7"
    db = SessionLocal()
    try:
        print("Initial cache stats:")
        print(get_cache_stats())
        print("Executing coding job...")
        await run_coding(claim_id, db=db)
        print("Final cache stats:")
        print(get_cache_stats())
        
        info = _search_icd10_rag_cached.cache_info()
        print(f"LRU Cache hits: {info.hits}, misses: {info.misses}, size: {info.currsize}")
    finally:
        db.close()

if __name__ == "__main__":
    import asyncio
    asyncio.run(test())
