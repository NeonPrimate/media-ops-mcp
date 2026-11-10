"""Radarr HTTP client (Movies).

Extends :class:`BaseArrClient` with Radarr-specific endpoints for movie
management, lookup, collections, and credits.
"""

from __future__ import annotations

import asyncio
from typing import Any

from arr_mcp.constants import DEFAULT_TIMEOUT, RADARR_API_PATH
from arr_mcp.services.base import BaseArrClient


class RadarrClient(BaseArrClient):
    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__(
            name="Radarr",
            base_url=base_url,
            api_key=api_key,
            api_path=RADARR_API_PATH,
            timeout=timeout,
        )

    # ── movies ────────────────────────────────────────────────────

    async def get_movies(self, tmdb_id: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if tmdb_id:
            params["tmdbId"] = tmdb_id
        return await self._get(f"{self.api_path}/movie", **params)  # type: ignore[return-value]

    async def get_movie(self, movie_id: int) -> dict[str, Any]:
        return await self._get(f"{self.api_path}/movie/{movie_id}")  # type: ignore[return-value]

    async def lookup_movie(self, term: str) -> list[dict[str, Any]]:
        return await self._get(f"{self.api_path}/movie/lookup", term=term)  # type: ignore[return-value]

    async def add_movie(
        self,
        tmdb_id: int,
        title: str,
        quality_profile_id: int,
        root_folder_path: str,
        monitored: bool = True,
        search_for_movie: bool = True,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tmdbId": tmdb_id,
            "title": title,
            "qualityProfileId": quality_profile_id,
            "rootFolderPath": root_folder_path,
            "monitored": monitored,
            "addOptions": {"searchForMovie": search_for_movie},
            **kwargs,
        }
        return await self._post(f"{self.api_path}/movie", json=payload)

    async def delete_movie(
        self, movie_id: int, delete_files: bool = False, add_import_list_exclusion: bool = False
    ) -> dict[str, Any]:
        return await self._delete(  # type: ignore[return-value]
            f"{self.api_path}/movie/{movie_id}",
            deleteFiles=delete_files,
            addImportExclusion=add_import_list_exclusion,
        )

    async def update_movie(self, movie_id: int, **fields: Any) -> dict[str, Any]:
        movie = await self.get_movie(movie_id)
        movie.update(fields)
        return await self._put(f"{self.api_path}/movie/{movie_id}", json=movie)

    # ── interactive release search ────────────────────────────────

    async def get_release_candidates(
        self,
        movie_id: int,
        *,
        attempts: int = 4,
        delay_seconds: float = 2.0,
    ) -> list[dict[str, Any]]:
        """Fetch interactive-search candidates, retrying while indexers respond."""
        for attempt in range(max(1, attempts)):
            releases = await self._get(  # type: ignore[return-value]
                f"{self.api_path}/release",
                movieId=movie_id,
                apikey=self.api_key,
            )
            if releases or attempt == max(1, attempts) - 1:
                return releases
            await asyncio.sleep(delay_seconds)
        return []

    async def grab_release(self, release: dict[str, Any]) -> dict[str, Any]:
        """Ask Radarr to grab an exact release returned by ``get_release_candidates``."""
        return await self._post(
            f"{self.api_path}/release",
            json=release,
            apikey=self.api_key,
        )

    # ── collections ───────────────────────────────────────────────

    async def get_collections(self, tmdb_id: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if tmdb_id:
            params["tmdbId"] = tmdb_id
        return await self._get(f"{self.api_path}/collection", **params)  # type: ignore[return-value]

    async def get_collection(self, collection_id: int) -> dict[str, Any]:
        return await self._get(f"{self.api_path}/collection/{collection_id}")  # type: ignore[return-value]

    # ── imports ───────────────────────────────────────────────────

    async def get_manual_import(
        self, folder: str | None = None, download_id: str | None = None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if folder:
            params["folder"] = folder
        if download_id:
            params["downloadId"] = download_id
        return await self._get(f"{self.api_path}/manualimport", **params)  # type: ignore[return-value]
