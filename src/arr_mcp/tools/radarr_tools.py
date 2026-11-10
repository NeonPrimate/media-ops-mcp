"""Radarr portmanteau tool - movie management.

All Radarr operations consolidated into a single ``radarr_movies`` tool with an
``operation`` discriminator.  Registered at import time via ``@mcp.tool()``
decorator.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StrictStr

from arr_mcp.constants import TOOL_VERSION

logger = logging.getLogger(__name__)


def _candidate_id(release: dict[str, Any]) -> str:
    """Create an opaque, non-sensitive reference for a Radarr candidate."""
    guid = release.get("guid")
    if not isinstance(guid, str) or not guid:
        raise ValueError("Radarr candidate has no usable guid")
    return hashlib.sha256(guid.encode("utf-8")).hexdigest()[:24]


def _compact_release(release: dict[str, Any], movie_id: int) -> dict[str, Any]:
    """Return useful candidate fields without exposing download URLs."""
    mapped_movie_id = release.get("mappedMovieId")
    candidate_movie_id = release.get("movieId")
    movie_match = mapped_movie_id == movie_id or candidate_movie_id == movie_id
    eligible = all((
        release.get("approved") is True,
        release.get("rejected") is False,
        release.get("temporarilyRejected") is False,
        release.get("downloadAllowed") is True,
        release.get("protocol") == "torrent",
        movie_match,
    ))
    quality = release.get("quality")
    quality_info = quality.get("quality") if isinstance(quality, dict) else {}
    return {
        "candidate_id": _candidate_id(release),
        "title": release.get("title"),
        "indexer": release.get("indexer"),
        "release_group": release.get("releaseGroup"),
        "quality": quality_info.get("name") if isinstance(quality_info, dict) else None,
        "size": release.get("size"),
        "seeders": release.get("seeders"),
        "protocol": release.get("protocol"),
        "approved": release.get("approved"),
        "rejected": release.get("rejected"),
        "temporarily_rejected": release.get("temporarilyRejected"),
        "download_allowed": release.get("downloadAllowed"),
        "rejections": release.get("rejections") or [],
        "eligible": eligible,
    }


def _recommendation_key(release: dict[str, Any]) -> str:
    title = str(release.get("title") or "").lower()
    return re.sub(r"[^a-z0-9]+", " ", title).strip()


def _release_score(release: dict[str, Any]) -> tuple[float, list[str]]:
    title = str(release.get("title") or "")
    lower = title.lower()
    quality = str(release.get("quality") or "").lower()
    seeders = release.get("seeders") if isinstance(release.get("seeders"), int) else 0
    size = release.get("size") if isinstance(release.get("size"), (int, float)) else 0
    score = {
        "bluray-1080p": 100,
        "remux-1080p": 95,
        "webdl-1080p": 88,
        "webrip-1080p": 82,
        "hdtv-1080p": 65,
        "bluray-2160p": 100,
        "remux-2160p": 95,
        "webdl-2160p": 88,
        "webrip-2160p": 82,
        "hdtv-2160p": 65,
    }.get(quality, 50)
    reasons: list[str] = []
    if "criterion" in lower:
        score += 35
        reasons.append("Criterion source")
    if "remaster" in lower:
        score += 10
        reasons.append("remastered release")
    if "bluray" in lower or "blu ray" in lower:
        score += 8
        reasons.append("Blu-ray source")
    if "x265" in lower or "hevc" in lower:
        score += 5
        reasons.append("HEVC/x265 encode")
    if "x264" in lower or "avc" in lower:
        score += 3
        reasons.append("broadly compatible x264/AVC encode")
    if "hdtv" in quality:
        score -= 12
        reasons.append("HDTV source")
    if "yts" in lower or "yify" in lower:
        score -= 2
        reasons.append("compact YTS/YIFY encode; expect more compression")
    score += min(max(seeders, 0), 200) / 8
    if seeders < 10:
        score -= 8
        reasons.append("availability risk: fewer than 10 seeders")
    if seeders:
        reasons.append(f"{seeders} seeders")
    if size:
        size_gb = size / 1_000_000_000
        if size_gb <= 4:
            score += max(0, 4 - size_gb) * 1.5
            reasons.append(f"{size_gb:.2f} GB")
        elif size_gb >= 20:
            score -= 8
            reasons.append(f"large {size_gb:.1f} GB release")
    return score, reasons


def _recommend_releases(releases: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    eligible = [release for release in releases if isinstance(release, dict) and release.get("eligible") is True]
    deduped: dict[str, dict[str, Any]] = {}
    for release in eligible:
        key = _recommendation_key(release)
        if not key:
            continue
        current = deduped.get(key)
        current_seeders = current.get("seeders") if current else -1
        release_seeders = release.get("seeders") if isinstance(release.get("seeders"), int) else 0
        if current is None or release_seeders > current_seeders:
            deduped[key] = release
    ranked: list[dict[str, Any]] = []
    for release in deduped.values():
        score, reasons = _release_score(release)
        item = dict(release)
        item["score"] = round(score, 2)
        item["reasons"] = reasons
        ranked.append(item)
    ranked.sort(key=lambda item: (-item["score"], -(item.get("seeders") or 0), item.get("size") or 0))
    return {
        "recommendations": ranked[:limit],
        "eligible_count": len(eligible),
        "deduplicated_count": len(ranked),
    }


def register_radarr_tools(mcp, client) -> None:
    """Register Radarr tools on the FastMCP instance."""
    # Always registered: `client` is a LiveClient proxy resolving the
    # current credentials per call (Settings → Services, no restart).

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def radarr_movies(
        operation: Annotated[
            Literal["list", "lookup", "get", "add", "search", "delete", "update", "import"],
            Field(
                description="Operation: list all, lookup by term, get by ID, add, search, delete, update, or import."
            ),
        ],
        term: Annotated[str | None, Field(description="Search term for lookup or add.")] = None,
        movie_id: Annotated[
            StrictInt | None, Field(description="Exact Radarr movie ID for get/search/delete/update.")
        ] = None,
        tmdb_id: Annotated[int | None, Field(description="TMDB ID for add operation.")] = None,
        title: Annotated[str | None, Field(description="Movie title for add operation.")] = None,
        quality_profile_id: Annotated[int | None, Field(description="Quality profile ID for add.")] = None,
        root_folder_path: Annotated[str | None, Field(description="Root folder path for add.")] = None,
        monitored: Annotated[bool, Field(description="Monitored status for add/update.")] = True,
        search_for_movie: Annotated[bool, Field(description="Search immediately after add.")] = True,
        delete_files: Annotated[bool, Field(description="Also delete files when deleting movie.")] = False,
        folder: Annotated[str | None, Field(description="Folder path for manual import.")] = None,
        add_import_list_exclusion: Annotated[
            bool, Field(description="When deleting, prevent import lists from adding this movie again. Defaults false.")
        ] = False,
    ) -> dict:
        """Manage Radarr movies: list, lookup, get, add, search, delete, update, import.

        ``lookup`` finds movie metadata. ``search`` starts Radarr's native
        MoviesSearch for one movie already in the library. The returned command
        confirms submission, not a completed download.

        On deletion, add_import_list_exclusion=true matches Add List Exclusion.
        This is independent of delete_files, which defaults to false.

        ## Return Format
        {"success": bool, "message": str, "data": [...]}

        ## Examples
        radarr_movies(operation="list")
        radarr_movies(operation="lookup", term="Dune")
        radarr_movies(operation="add", tmdb_id=438631, quality_profile_id=1, root_folder_path="/movies")
        radarr_movies(operation="search", movie_id=42)
        radarr_movies(operation="delete", movie_id=42, delete_files=True)
        radarr_movies(operation="delete", movie_id=42, add_import_list_exclusion=True)
        """
        try:
            if operation == "list":
                data = await client.get_movies()
                return {"success": True, "message": f"Found {len(data)} movies", "data": data}

            if operation == "lookup":
                if not term:
                    return {"success": False, "message": "term is required for lookup", "data": []}
                data = await client.lookup_movie(term)
                return {"success": True, "message": f"Found {len(data)} results for '{term}'", "data": data}

            if operation == "get":
                if not movie_id:
                    return {"success": False, "message": "movie_id is required for get", "data": {}}
                data = await client.get_movie(movie_id)
                return {"success": True, "message": f"Movie {movie_id}", "data": data}

            if operation == "add":
                if not tmdb_id or not quality_profile_id or not root_folder_path:
                    return {
                        "success": False,
                        "message": "tmdb_id, quality_profile_id, and root_folder_path are required",
                        "data": {},
                    }
                data = await client.add_movie(
                    tmdb_id=tmdb_id,
                    title=title or "",
                    quality_profile_id=quality_profile_id,
                    root_folder_path=root_folder_path,
                    monitored=monitored,
                    search_for_movie=search_for_movie,
                )
                return {"success": True, "message": f"Added '{title or data.get('title', '')}'", "data": data}

            if operation == "search":
                if isinstance(movie_id, bool) or not isinstance(movie_id, int) or movie_id <= 0:
                    return {"success": False, "message": "A positive exact movie_id is required for search", "data": {}}
                movie = await client.get_movie(movie_id)
                if not isinstance(movie, dict) or type(movie.get("id")) is not int or movie["id"] != movie_id:
                    return {
                        "success": False,
                        "message": f"Radarr returned a mismatched movie ID for requested movie {movie_id}; search was not started",
                        "data": {},
                    }
                command = await client.trigger_command("MoviesSearch", movieIds=[movie_id])
                return {
                    "success": True,
                    "message": f"Submitted Radarr search for '{movie.get('title', movie_id)}' (movie {movie_id})",
                    "data": command,
                }

            if operation == "delete":
                if not movie_id:
                    return {"success": False, "message": "movie_id is required for delete", "data": {}}
                await client.delete_movie(
                    movie_id, delete_files=delete_files, add_import_list_exclusion=add_import_list_exclusion
                )
                return {"success": True, "message": f"Deleted movie {movie_id}", "data": {}}

            if operation == "update":
                if not movie_id:
                    return {"success": False, "message": "movie_id is required for update", "data": {}}
                data = await client.update_movie(movie_id, monitored=monitored)
                return {"success": True, "message": f"Updated movie {movie_id}", "data": data}

            if operation == "import":
                data = await client.get_manual_import(folder=folder)
                return {"success": True, "message": f"Found {len(data)} items to import", "data": data}

            return {"success": False, "message": f"Unknown operation: {operation}", "data": {}}

        except Exception as e:
            logger.exception("radarr_movies failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}


    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def radarr_release_search(
        movie_id: Annotated[StrictInt, Field(description="Exact Radarr movie ID to search.")],
    ) -> dict:
        """List compact interactive-search candidates for one movie.

        Magnet/download URLs are intentionally omitted. Review the title,
        quality, size, and release group before using ``radarr_release_grab``.
        """
        try:
            if isinstance(movie_id, bool) or movie_id <= 0:
                return {"success": False, "message": "A positive movie_id is required", "data": []}
            releases = await client.get_release_candidates(movie_id)
            data = [_compact_release(release, movie_id) for release in releases if isinstance(release, dict)]
            eligible_count = sum(1 for release in data if release["eligible"])
            return {
                "success": True,
                "message": f"Found {len(data)} release candidates; {eligible_count} passed basic safety checks",
                "data": data,
            }
        except Exception as e:
            logger.exception("radarr_release_search failed: %s", e)
            return {"success": False, "message": str(e), "data": []}

    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def radarr_release_recommend(
        movie_id: Annotated[StrictInt, Field(description="Exact Radarr movie ID.")],
        limit: Annotated[StrictInt, Field(description="Number of options to return (1-4).", ge=1, le=4)] = 4,
    ) -> dict:
        """Return a short, deterministic ranked list of eligible Radarr releases.

        This is a recommendation/filtering operation only. It never submits a grab.
        Use ``radarr_release_grab`` only after the user selects a candidate.
        """
        try:
            if isinstance(movie_id, bool) or movie_id <= 0:
                return {"success": False, "message": "A positive movie_id is required", "data": {}}
            releases = await client.get_release_candidates(movie_id)
            compact = [_compact_release(release, movie_id) for release in releases if isinstance(release, dict)]
            recommendation = _recommend_releases(compact, limit)
            recommendation["candidate_count"] = len(compact)
            return {
                "success": True,
                "message": (
                    f"Ranked {len(recommendation['recommendations'])} recommendations from "
                    f"{recommendation['eligible_count']} eligible candidates"
                ),
                "data": recommendation,
            }
        except Exception as e:
            logger.exception("radarr_release_recommend failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def radarr_release_grab(
        movie_id: Annotated[StrictInt, Field(description="Exact Radarr movie ID.")],
        candidate_id: Annotated[StrictStr, Field(description="Opaque candidate_id returned by radarr_release_search.")],
    ) -> dict:
        """Refetch and grab one explicitly selected, eligible Radarr release."""
        try:
            if isinstance(movie_id, bool) or movie_id <= 0:
                return {"success": False, "message": "A positive movie_id is required", "data": {}}
            if not candidate_id:
                return {"success": False, "message": "candidate_id is required", "data": {}}

            releases = await client.get_release_candidates(movie_id)
            matches = [
                release
                for release in releases
                if isinstance(release, dict) and _candidate_id(release) == candidate_id
            ]
            if len(matches) != 1:
                return {
                    "success": False,
                    "message": f"Expected exactly one matching release candidate, found {len(matches)}; nothing was grabbed",
                    "data": {},
                }

            release = matches[0]
            compact = _compact_release(release, movie_id)
            if not compact["eligible"]:
                return {
                    "success": False,
                    "message": "Selected release failed Radarr safety checks; nothing was grabbed",
                    "data": compact,
                }

            result = await client.grab_release(release)
            return {
                "success": True,
                "message": f"Submitted '{release.get('title', 'selected release')}' to Radarr",
                "data": {"candidate": compact, "radarr": result},
            }
        except Exception as e:
            logger.exception("radarr_release_grab failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}
