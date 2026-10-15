"""Call recordings in Supabase Storage (a private bucket), played back through short-lived signed links.

Needs SUPABASE_SERVICE_ROLE_KEY (server only: it bypasses row level security, never send it to the browser) and the
project URL. Without them, LeadPilot keeps the phone system's own recording link instead.
"""
from __future__ import annotations

import os

DEFAULT_BUCKET = "call-recordings"
MAX_BYTES = 100 * 1024 * 1024
TYPES = {"wav": "audio/wav", "mp3": "audio/mpeg", "m4a": "audio/mp4", "ogg": "audio/ogg", "webm": "audio/webm"}


class StorageError(Exception):
    pass


class RecordingStore:
    def __init__(self, supabase_url: str | None, env: dict | None = None, transport=None):
        env = os.environ if env is None else env
        key = (env.get("SUPABASE_SERVICE_ROLE_KEY") or "").strip()
        self.key = key if key and "<" not in key else None
        self.url = (supabase_url or "").rstrip("/") or None
        self.bucket = (env.get("LEADPILOT_RECORDINGS_BUCKET") or "").strip() or DEFAULT_BUCKET
        self.transport = transport
        self._bucket_ready = False

    @property
    def configured(self) -> bool:
        return bool(self.key and self.url)

    def _headers(self, **extra) -> dict:
        return {"Authorization": f"Bearer {self.key}", "apikey": self.key, **extra}

    def client(self):
        import httpx
        return httpx.AsyncClient(timeout=120.0, transport=self.transport, follow_redirects=True)

    async def _ensure_bucket(self, client) -> None:
        if self._bucket_ready:
            return
        r = await client.post(f"{self.url}/storage/v1/bucket", headers=self._headers(),
                              json={"id": self.bucket, "name": self.bucket, "public": False})
        if r.status_code < 300 or "already exists" in r.text.lower() or r.status_code == 409:
            self._bucket_ready = True
            return
        raise StorageError(f"could not create the {self.bucket} bucket: HTTP {r.status_code} {r.text[:200]}")

    async def copy_from(self, source_url: str, path_stem: str) -> str:
        """Download the phone system's recording and keep a private copy. Returns the object path."""
        if not self.configured:
            raise StorageError("recording storage is not set up")
        async with self.client() as client:
            src = await client.get(source_url)
            if src.status_code >= 400:
                raise StorageError(f"could not download the recording: HTTP {src.status_code}")
            data = src.content
            if len(data) > MAX_BYTES:
                raise StorageError("the recording is larger than 100 MB")
            ext = source_url.split("?")[0].rsplit(".", 1)[-1].lower()
            ext = ext if ext in TYPES else "wav"
            ctype = src.headers.get("content-type", "").split(";")[0] or TYPES[ext]
            path = f"{path_stem}.{ext}"
            await self._ensure_bucket(client)
            up = await client.post(f"{self.url}/storage/v1/object/{self.bucket}/{path}", content=data,
                                   headers=self._headers(**{"Content-Type": ctype, "x-upsert": "true"}))
            if up.status_code >= 300:
                raise StorageError(f"could not store the recording: HTTP {up.status_code} {up.text[:200]}")
        return path

    async def signed_url(self, path: str, seconds: int = 3600) -> str:
        if not self.configured:
            raise StorageError("recording storage is not set up")
        async with self.client() as client:
            r = await client.post(f"{self.url}/storage/v1/object/sign/{self.bucket}/{path}", headers=self._headers(),
                                  json={"expiresIn": seconds})
        if r.status_code >= 300:
            raise StorageError(f"could not sign the recording link: HTTP {r.status_code}")
        signed = r.json().get("signedURL") or r.json().get("signedUrl") or ""
        return signed if signed.startswith("http") else f"{self.url}/storage/v1{signed}"
