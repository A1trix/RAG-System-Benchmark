import redis
from rq import Queue


def get_queue(redis_url: str, name: str):
    conn = redis.from_url(redis_url)
    return Queue(name, connection=conn, default_timeout=600)
