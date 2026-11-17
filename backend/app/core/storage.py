"""Object storage for reports, exports and model artifacts (MinIO, Ch. 3.3.4).

Falls back to the local filesystem when MinIO is not configured so that report
generation and model training work in a laptop-only setup.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.resilience import BREAKERS

log = get_logger(__name__)


class ObjectStore(Protocol):
    backend: str

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, bucket: str, key: str) -> bytes: ...
    async def health(self) -> dict[str, object]: ...


class LocalStore:
    backend = "local"

    def __init__(self, root: str) -> None:
        self.root = Path(root)

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> str:
        path = self.root / bucket / key
        path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        return f"file://{path.resolve()}"

    async def get(self, bucket: str, key: str) -> bytes:
        return await asyncio.to_thread((self.root / bucket / key).read_bytes)

    async def health(self) -> dict[str, object]:
        return {"status": "degraded", "backend": "local", "latency_ms": 0}


class MinioStore:
    backend = "minio"

    def __init__(self, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        from minio import Minio

        self.client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
        self._ready: set[str] = set()

    def _ensure(self, bucket: str) -> None:
        if bucket not in self._ready:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
            self._ready.add(bucket)

    async def put(self, bucket: str, key: str, data: bytes, content_type: str) -> str:
        def _put() -> None:
            self._ensure(bucket)
            self.client.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)

        await asyncio.to_thread(BREAKERS["minio"].call, _put)
        return f"s3://{bucket}/{key}"

    async def get(self, bucket: str, key: str) -> bytes:
        def _get() -> bytes:
            resp = self.client.get_object(bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await asyncio.to_thread(BREAKERS["minio"].call, _get)

    async def health(self) -> dict[str, object]:
        import time

        start = time.perf_counter()
        try:
            await asyncio.wait_for(asyncio.to_thread(self.client.list_buckets), timeout=2)
            return {"status": "healthy", "backend": "minio",
                    "latency_ms": round((time.perf_counter() - start) * 1000, 1)}
        except Exception as exc:  # noqa: BLE001
            return {"status": "unhealthy", "backend": "minio", "error": str(exc)}


_store: ObjectStore | None = None


def get_store() -> ObjectStore:
    global _store
    if _store is None:
        s = get_settings()
        if s.minio_endpoint and s.minio_access_key and s.minio_secret_key:
            try:
                _store = MinioStore(s.minio_endpoint, s.minio_access_key, s.minio_secret_key, s.minio_secure)
                log.info("object_store", backend="minio", endpoint=s.minio_endpoint)
            except Exception as exc:  # noqa: BLE001
                log.warning("object_store_degraded", backend="local", reason=str(exc))
                _store = LocalStore(s.local_storage_dir)
        else:
            _store = LocalStore(s.local_storage_dir)
    return _store
