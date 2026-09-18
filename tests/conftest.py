"""Foundation test setup: dummy config so service modules import WITHOUT
live Postgres/Redis, and zero AI latency so the suite stays fast.
DB/Redis-touching paths are integration tests (need the stack); everything
here must pass with no engine, no network, no containers.
"""
import os

os.environ.setdefault("DATABASE_URL", "postgresql://app:dummy@127.0.0.1:5432/healthcare")
os.environ.setdefault("REDIS_URL", "redis://:dummy@127.0.0.1:6379/0")
os.environ.setdefault("AI_LATENCY_SEC", "0")
