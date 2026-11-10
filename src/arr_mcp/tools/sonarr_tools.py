"""Sonarr portmanteau tools - series & episode management."""

from __future__ import annotations

import hashlib
import logging
from typing import Annotated, Any, Literal

from pydantic import Field, StrictInt, StrictStr

from arr_mcp.constants import TOOL_VERSION

logger = logging.getLogger(__name__)


def _candidate_id(release: dict[str, Any]) -> str:
    """Create an opaque, non-sensitive reference for a Sonarr candidate."""
    guid = release.get("guid")
    if not isinstance(guid, str) or not guid:
        raise ValueError("Sonarr candidate has no usable guid")
    return hashlib.sha256(guid.encode("utf-8")).hexdigest()[:24]


def _compact_release(release: dict[str, Any], episode_id: int) -> dict[str, Any]:
    """Return useful candidate fields without exposing magnet URLs."""
    quality = release.get("quality")
    quality_info = quality.get("quality") if isinstance(quality, dict) else {}
    mapped_info = release.get("mappedEpisodeInfo")
    episode_match = any(
        isinstance(item, dict) and item.get("id") == episode_id
        for item in (mapped_info if isinstance(mapped_info, list) else [])
    )
    episode_match = episode_match or episode_id in (release.get("episodeIds") or [])
    eligible = all(
        (release.get("approved") is True,
         release.get("rejected") is False,
         release.get("temporarilyRejected") is False,
         release.get("downloadAllowed") is True,
         release.get("protocol") == "torrent",
         episode_match)
    )
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


def register_sonarr_tools(mcp, client) -> None:
    # Always registered: `client` is a LiveClient proxy resolving the
    # current credentials per call (Settings → Services, no restart).

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def sonarr_series(
        operation: Annotated[
            Literal["list", "lookup", "get", "add", "search", "delete", "update"],
            Field(description="Operation: list all, lookup by term, get by ID, add, search, delete, or update."),
        ],
        term: Annotated[str | None, Field(description="Search term for lookup.")] = None,
        series_id: Annotated[
            StrictInt | None, Field(description="Exact Sonarr series ID for get/search/delete/update.")
        ] = None,
        tvdb_id: Annotated[int | None, Field(description="TVDB ID for add operation.")] = None,
        title: Annotated[str | None, Field(description="Series title for add.")] = None,
        quality_profile_id: Annotated[int | None, Field(description="Quality profile ID for add.")] = None,
        root_folder_path: Annotated[str | None, Field(description="Root folder path for add.")] = None,
        monitored: Annotated[bool, Field(description="Monitored status for add/update.")] = True,
        search_for_missing: Annotated[bool, Field(description="Search for missing episodes after add.")] = True,
        delete_files: Annotated[bool, Field(description="Also delete files when deleting series.")] = False,
        add_import_list_exclusion: Annotated[
            bool,
            Field(description="When deleting, prevent import lists from adding this series again. Defaults false."),
        ] = False,
    ) -> dict:
        """Manage Sonarr series: list, lookup, get, add, search, delete, update.

        ``lookup`` finds series metadata. ``search`` starts Sonarr's native
        SeriesSearch for one series already in the library. The returned command
        confirms submission, not completed downloads.

        On deletion, add_import_list_exclusion=true matches Add List Exclusion.
        This is independent of delete_files, which defaults to false.

        ## Return Format
        {"success": bool, "message": str, "data": [...]}

        ## Examples
        sonarr_series(operation="list")
        sonarr_series(operation="lookup", term="Breaking Bad")
        sonarr_series(operation="search", series_id=42)
        sonarr_series(operation="delete", series_id=42, add_import_list_exclusion=True)
        sonarr_series(operation="add", tvdb_id=81189, quality_profile_id=1, root_folder_path="/tv")
        """
        try:
            if operation == "list":
                data = await client.get_series()
                return {"success": True, "message": f"Found {len(data)} series", "data": data}

            if operation == "lookup":
                if not term:
                    return {"success": False, "message": "term is required for lookup", "data": []}
                data = await client.lookup_series(term)
                return {"success": True, "message": f"Found {len(data)} results for '{term}'", "data": data}

            if operation == "get":
                if not series_id:
                    return {"success": False, "message": "series_id is required for get", "data": {}}
                data = await client.get_series_by_id(series_id)
                return {"success": True, "message": f"Series {series_id}", "data": data}

            if operation == "add":
                if not tvdb_id or not quality_profile_id or not root_folder_path:
                    return {
                        "success": False,
                        "message": "tvdb_id, quality_profile_id, and root_folder_path are required",
                        "data": {},
                    }
                data = await client.add_series(
                    tvdb_id=tvdb_id,
                    title=title or "",
                    quality_profile_id=quality_profile_id,
                    root_folder_path=root_folder_path,
                    monitored=monitored,
                    search_for_missing_episodes=search_for_missing,
                )
                return {"success": True, "message": f"Added '{title or data.get('title', '')}'", "data": data}

            if operation == "search":
                if isinstance(series_id, bool) or not isinstance(series_id, int) or series_id <= 0:
                    return {
                        "success": False,
                        "message": "A positive exact series_id is required for search",
                        "data": {},
                    }
                series = await client.get_series_by_id(series_id)
                if not isinstance(series, dict) or type(series.get("id")) is not int or series["id"] != series_id:
                    return {
                        "success": False,
                        "message": f"Sonarr returned a mismatched series ID for requested series {series_id}; search was not started",
                        "data": {},
                    }
                command = await client.trigger_command("SeriesSearch", seriesId=series_id)
                return {
                    "success": True,
                    "message": f"Submitted Sonarr search for '{series.get('title', series_id)}' (series {series_id})",
                    "data": command,
                }

            if operation == "delete":
                if not series_id:
                    return {"success": False, "message": "series_id is required for delete", "data": {}}
                await client.delete_series(
                    series_id, delete_files=delete_files, add_import_list_exclusion=add_import_list_exclusion
                )
                return {"success": True, "message": f"Deleted series {series_id}", "data": {}}

            if operation == "update":
                if not series_id:
                    return {"success": False, "message": "series_id is required for update", "data": {}}
                data = await client.update_series(series_id, monitored=monitored)
                return {"success": True, "message": f"Updated series {series_id}", "data": data}

            return {"success": False, "message": f"Unknown operation: {operation}", "data": {}}

        except Exception as e:
            logger.exception("sonarr_series failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def sonarr_episodes(
        operation: Annotated[
            Literal["list", "get", "search", "set_monitored"],
            Field(
                description="Operation: list episodes, get by ID, search one episode or a whole season, set monitored status."
            ),
        ],
        series_id: Annotated[
            StrictInt | None, Field(description="Exact Sonarr series ID for listing or searching a season.")
        ] = None,
        season_number: Annotated[
            StrictInt | None, Field(description="Exact season number for filtering or searching; 0 selects specials.")
        ] = None,
        episode_id: Annotated[
            StrictInt | None, Field(description="Exact Sonarr episode ID for get/search/set_monitored.")
        ] = None,
        monitored: Annotated[bool, Field(description="Monitored status for set_monitored.")] = True,
    ) -> dict:
        """Manage Sonarr episodes: list, get, search an episode or season, set monitored.

        For ``search``, pass exactly one ``episode_id`` to search an individual
        episode, or pass ``series_id`` and ``season_number`` to search a whole
        season. Use ``sonarr_series(operation="search", ...)`` for a whole series.

        ## Return Format
        {"success": bool, "message": str, "data": [...]}

        ## Examples
        sonarr_episodes(operation="list", series_id=123)
        sonarr_episodes(operation="search", episode_id=456)
        sonarr_episodes(operation="search", series_id=123, season_number=2)
        sonarr_episodes(operation="set_monitored", episode_id=456, monitored=False)
        """
        try:
            if operation == "list":
                if not series_id:
                    return {"success": False, "message": "series_id is required for list", "data": []}
                data = await client.get_episodes(series_id, season_number=season_number)
                return {"success": True, "message": f"Found {len(data)} episodes", "data": data}

            if operation == "get":
                if not episode_id:
                    return {"success": False, "message": "episode_id is required for get", "data": {}}
                data = await client.get_episode(episode_id)
                return {"success": True, "message": f"Episode {episode_id}", "data": data}

            if operation == "search":
                has_episode = isinstance(episode_id, int) and not isinstance(episode_id, bool) and episode_id > 0
                has_series = isinstance(series_id, int) and not isinstance(series_id, bool) and series_id > 0
                has_season = (
                    isinstance(season_number, int) and not isinstance(season_number, bool) and season_number >= 0
                )

                if has_episode and series_id is None and season_number is None:
                    episode = await client.get_episode(episode_id)
                    if (
                        not isinstance(episode, dict)
                        or type(episode.get("id")) is not int
                        or episode["id"] != episode_id
                    ):
                        return {
                            "success": False,
                            "message": f"Sonarr returned a mismatched episode ID for requested episode {episode_id}; search was not started",
                            "data": {},
                        }
                    command = await client.trigger_command("EpisodeSearch", episodeIds=[episode_id])
                    return {
                        "success": True,
                        "message": f"Submitted Sonarr search for '{episode.get('title', episode_id)}' (episode {episode_id})",
                        "data": command,
                    }

                if episode_id is None and has_series and has_season:
                    series = await client.get_series_by_id(series_id)
                    if not isinstance(series, dict) or type(series.get("id")) is not int or series["id"] != series_id:
                        return {
                            "success": False,
                            "message": f"Sonarr returned a mismatched series ID for requested series {series_id}; search was not started",
                            "data": {},
                        }
                    seasons = series.get("seasons")
                    if isinstance(seasons, list) and not any(
                        isinstance(season, dict) and season.get("seasonNumber") == season_number for season in seasons
                    ):
                        return {
                            "success": False,
                            "message": f"Season {season_number} does not exist in Sonarr series {series_id}; search was not started",
                            "data": {},
                        }
                    command = await client.trigger_command(
                        "SeasonSearch", seriesId=series_id, seasonNumber=season_number
                    )
                    return {
                        "success": True,
                        "message": f"Submitted Sonarr search for season {season_number} of '{series.get('title', series_id)}'",
                        "data": command,
                    }

                return {
                    "success": False,
                    "message": "Search requires exactly one positive episode_id, or a positive series_id with a non-negative season_number",
                    "data": {},
                }

            if operation == "set_monitored":
                if not episode_id:
                    return {"success": False, "message": "episode_id is required for set_monitored", "data": {}}
                data = await client.update_episode(episode_id, monitored=monitored)
                return {"success": True, "message": f"Episode {episode_id} monitored={monitored}", "data": data}

            return {"success": False, "message": f"Unknown operation: {operation}", "data": {}}

        except Exception as e:
            logger.exception("sonarr_episodes failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}


    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def sonarr_release_search(
        episode_id: Annotated[StrictInt, Field(description="Exact Sonarr episode ID to search.")],
    ) -> dict:
        """List compact interactive-search candidates for one episode.

        Candidate IDs are opaque references. Magnet URLs and API credentials are
        intentionally omitted from the result. ``eligible`` only means the
        candidate passed Sonarr's basic safety checks; review the title and
        quality before using ``sonarr_release_grab``.
        """
        try:
            if isinstance(episode_id, bool) or episode_id <= 0:
                return {"success": False, "message": "A positive episode_id is required", "data": []}
            releases = await client.get_release_candidates(episode_id)
            data = [_compact_release(release, episode_id) for release in releases if isinstance(release, dict)]
            eligible_count = sum(1 for release in data if release["eligible"])
            return {
                "success": True,
                "message": f"Found {len(data)} release candidates; {eligible_count} passed basic safety checks",
                "data": data,
            }
        except Exception as e:
            logger.exception("sonarr_release_search failed: %s", e)
            return {"success": False, "message": str(e), "data": []}

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def sonarr_release_grab(
        episode_id: Annotated[StrictInt, Field(description="Exact Sonarr episode ID.")],
        candidate_id: Annotated[StrictStr, Field(description="Opaque candidate_id returned by sonarr_release_search.")],
    ) -> dict:
        """Refetch and grab one explicitly selected, eligible Sonarr release.

        The model supplies only the opaque candidate ID. The full release object
        is refetched from Sonarr and validated server-side before POSTing it.
        """
        try:
            if isinstance(episode_id, bool) or episode_id <= 0:
                return {"success": False, "message": "A positive episode_id is required", "data": {}}
            if not candidate_id:
                return {"success": False, "message": "candidate_id is required", "data": {}}

            releases = await client.get_release_candidates(episode_id)
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
            compact = _compact_release(release, episode_id)
            if not compact["eligible"]:
                return {
                    "success": False,
                    "message": "Selected release failed Sonarr safety checks; nothing was grabbed",
                    "data": compact,
                }

            result = await client.grab_release(release)
            return {
                "success": True,
                "message": f"Submitted '{release.get('title', 'selected release')}' to Sonarr",
                "data": {"candidate": compact, "sonarr": result},
            }
        except Exception as e:
            logger.exception("sonarr_release_grab failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}
