import asyncio
import json
import logging
import signal
import sys

from rq import Worker

from rag_service.config import Settings
from rag_service.ingest import ingest_document
from rag_service.db import create_pool, close_pool, get_pool_stats
from rag_service.workers.queue import get_queue

logger = logging.getLogger(__name__)


async def main_async():
    settings = Settings()
    
    # Create worker-optimized pool (min_size=2, max_size=6)
    pool = await create_pool(settings, is_worker=True)
    
    # Log pool stats on startup
    stats = get_pool_stats(pool)
    logger.info("Worker pool initialized: %s", stats)
    
    queue = get_queue(settings.redis_url, settings.queue_name)

    async def handle(job):
        payload = json.loads(job.description)
        await ingest_document(payload, settings, pool)

    worker = Worker([queue])
    
    # Set up graceful shutdown with proper pool cleanup
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        logger.info("Received signal %d, shutting down gracefully...", signum)
        shutdown_event.set()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        # Run worker with proper cleanup on shutdown
        worker.work()
    except Exception as e:
        logger.error("Worker error: %s", e, exc_info=True)
        raise
    finally:
        # Ensure pool is always closed on shutdown
        logger.info("Closing worker database pool...")
        await close_pool(pool)
        logger.info("Worker shutdown complete")


def main():
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        logger.info("Worker stopped by user")
    except Exception as e:
        logger.error("Worker failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
