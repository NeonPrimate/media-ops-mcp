"""Small read-only qBittorrent Web API client.

Authentication prefers an API key when the server accepts ``X-Api-Key`` and
falls back to the documented WebUI username/password session login.
"""

from __future__ import annotations

from typing import Any

import httpx


class QBittorrentError(RuntimeError):
    """Raised when qBittorrent cannot be reached or authenticated."""


class QBittorrentClient:
    """Async qBittorrent Web API client with read-only operations."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        api_key: str = "",
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.api_key = api_key
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._authenticated = False

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"X-Api-Key": self.api_key} if self.api_key else {}
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        if not self._authenticated:
            await self._authenticate()
        return self._client

    async def _authenticate(self) -> None:
        client = self._client
        assert client is not None
        if self.api_key:
            response = await client.get("/api/v2/app/version")
            if response.is_success:
                self._authenticated = True
                return
        if not self.username or not self.password:
            raise QBittorrentError("qBittorrent requires an API key or username/password")
        response = await client.post(
            "/api/v2/auth/login",
            data={"username": self.username, "password": self.password},
        )
        body = response.text.strip().lower()
        if response.status_code not in {200, 204} or (body and body not in {"ok.", "ok"}):
            raise QBittorrentError(f"qBittorrent login failed (HTTP {response.status_code})")
        self._authenticated = True

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()
        self._client = None
        self._authenticated = False

    async def _get(self, path: str, **params: Any) -> Any:
        client = await self._ensure_client()
        response = await client.get(path, params=params)
        if response.status_code in {401, 403} and self.username and self.password:
            self._authenticated = False
            await self._authenticate()
            response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def get_version(self) -> str:
        client = await self._ensure_client()
        response = await client.get("/api/v2/app/version")
        if response.status_code in {401, 403} and self.username and self.password:
            self._authenticated = False
            await self._authenticate()
            response = await client.get("/api/v2/app/version")
        response.raise_for_status()
        return response.text.strip().strip('\"')

    async def health_check(self) -> dict[str, Any]:
        return {"version": await self.get_version()}

    async def get_torrents(self, *, state_filter: str | None = None, category: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if state_filter:
            params["filter"] = state_filter
        if category:
            params["category"] = category
        return await self._get("/api/v2/torrents/info", **params)

    async def get_torrent(self, torrent_hash: str) -> dict[str, Any]:
        return await self._get("/api/v2/torrents/properties", hash=torrent_hash)

    async def get_torrent_files(self, torrent_hash: str) -> list[dict[str, Any]]:
        return await self._get("/api/v2/torrents/files", hash=torrent_hash)

    async def get_transfer_info(self) -> dict[str, Any]:
        return await self._get("/api/v2/transfer/info")
