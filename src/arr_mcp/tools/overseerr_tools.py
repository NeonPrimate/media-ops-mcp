"""Overseerr portmanteau tool - media requests & discovery management."""

from __future__ import annotations

import logging
from datetime import date
from typing import Annotated, Any, Literal

from pydantic import Field

from arr_mcp.constants import TOOL_VERSION

logger = logging.getLogger(__name__)

_RELEASE_TYPE_NAMES = {
    1: "premiere",
    2: "theatrical_limited",
    3: "theatrical",
    4: "digital",
    5: "physical",
    6: "tv",
}


def _release_summary(details: dict[str, Any], region: str) -> dict[str, Any]:
    """Normalize Seerr/TMDB release dates without returning the full response."""
    countries = details.get("releases", {}).get("results", [])
    country = next((item for item in countries if item.get("iso_3166_1") == region), None)
    release_dates = country.get("release_dates", []) if isinstance(country, dict) else []
    mapped = []
    for item in release_dates:
        raw_date = item.get("release_date")
        if not raw_date:
            continue
        mapped.append({
            "date": raw_date[:10],
            "type": _RELEASE_TYPE_NAMES.get(item.get("type"), f"type_{item.get('type')}"),
            "certification": item.get("certification") or None,
            "note": item.get("note") or None,
        })
    mapped.sort(key=lambda item: item["date"])

    def first_date(kind: str) -> str | None:
        values = [item["date"] for item in mapped if item["type"] == kind]
        return min(values) if values else None

    broad_dates = [
        item["date"]
        for item in mapped
        if item["type"] in {"digital", "physical", "tv"}
    ]
    theatrical_dates = [
        item["date"]
        for item in mapped
        if item["type"] in {"theatrical", "theatrical_limited"}
    ]
    broad_date = min(broad_dates) if broad_dates else None
    if broad_date is None:
        availability_status = "theatrical_only_known" if theatrical_dates else "digital_unknown"
    elif broad_date <= date.today().isoformat():
        availability_status = "released"
    else:
        availability_status = "upcoming"

    return {
        "tmdb_id": details.get("id"),
        "title": details.get("title"),
        "region": region,
        "release_dates": mapped,
        "theatrical_release": min(theatrical_dates) if theatrical_dates else None,
        "digital_release": first_date("digital"),
        "physical_release": first_date("physical"),
        "tv_release": first_date("tv"),
        "widely_available_date": broad_date,
        "availability_status": availability_status,
        "status": details.get("status"),
        "overview": details.get("overview"),
        "watch_providers": details.get("watchProviders") or [],
    }


def register_overseerr_tools(mcp, client) -> None:
    # Always registered: `client` is a LiveClient proxy resolving the
    # current credentials per call (Settings → Services, no restart).

    @mcp.tool(
        annotations={"readOnlyHint": False, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def overseerr_requests(
        operation: Annotated[
            Literal["list", "get", "create", "approve", "decline", "delete", "count", "pending"],
            Field(
                description="Operation: list all, get by ID, create, approve, decline, delete, count, or view pending."
            ),
        ],
        request_id: Annotated[int | None, Field(description="Request ID for get/approve/decline/delete.")] = None,
        media_type: Annotated[str | None, Field(description="Media type: 'movie' or 'tv' for create.")] = None,
        media_id: Annotated[int | None, Field(description="TMDB ID for create.")] = None,
        tvdb_id: Annotated[int | None, Field(description="TVDB ID for TV requests.")] = None,
        seasons: Annotated[list[int] | None, Field(description="Season numbers for TV requests.")] = None,
        is4k: Annotated[bool, Field(description="Request 4K quality.")] = False,
        request_filter: Annotated[
            str, Field(description="Filter: 'all', 'approved', 'available', 'pending', 'processing', 'failed'.")
        ] = "all",
        take: Annotated[int, Field(description="Results per page.")] = 20,
        skip: Annotated[int, Field(description="Offset for pagination.")] = 0,
    ) -> dict:
        """Manage Overseerr media requests: view, create, approve, decline, delete.

        Overseerr is the user-facing request gateway for the *arr stack.
        Users request movies/TV shows through Overseerr, which routes to
        Radarr/Sonarr for fulfillment.

        ## Return Format
        {"success": bool, "message": str, "data": [...]}

        ## Examples
        overseerr_requests(operation="list", filter="pending")
        overseerr_requests(operation="create", media_type="movie", media_id=438631)
        overseerr_requests(operation="approve", request_id=42)
        overseerr_requests(operation="count")
        """
        try:
            if operation == "list":
                data = await client.get_requests(take=take, skip=skip, request_filter=request_filter)
                return {"success": True, "message": f"Found {len(data.get('results', []))} requests", "data": data}

            if operation == "pending":
                data = await client.get_requests(take=take, skip=skip, request_filter="pending")
                return {
                    "success": True,
                    "message": f"Found {len(data.get('results', []))} pending requests",
                    "data": data,
                }

            if operation == "get":
                if not request_id:
                    return {"success": False, "message": "request_id is required for get", "data": {}}
                data = await client.get_request(request_id)
                return {"success": True, "message": f"Request {request_id}", "data": data}

            if operation == "create":
                if not media_type or not media_id:
                    return {"success": False, "message": "media_type and media_id are required", "data": {}}
                data = await client.create_request(
                    media_type=media_type,
                    media_id=media_id,
                    tvdb_id=tvdb_id,
                    seasons=seasons,
                    is4k=is4k,
                )
                return {"success": True, "message": f"Created {media_type} request {media_id}", "data": data}

            if operation == "approve":
                if not request_id:
                    return {"success": False, "message": "request_id is required for approve", "data": {}}
                data = await client.approve_request(request_id)
                return {"success": True, "message": f"Approved request {request_id}", "data": data}

            if operation == "decline":
                if not request_id:
                    return {"success": False, "message": "request_id is required for decline", "data": {}}
                data = await client.decline_request(request_id)
                return {"success": True, "message": f"Declined request {request_id}", "data": data}

            if operation == "delete":
                if not request_id:
                    return {"success": False, "message": "request_id is required for delete", "data": {}}
                await client.delete_request(request_id)
                return {"success": True, "message": f"Deleted request {request_id}", "data": {}}

            if operation == "count":
                data = await client.get_request_count()
                return {"success": True, "message": "Request counts", "data": data}

            return {"success": False, "message": f"Unknown operation: {operation}", "data": {}}

        except Exception as e:
            logger.exception("overseerr_requests failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}

    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def overseerr_search(
        query: Annotated[str, Field(description="Search query for movies, TV shows, and people.")],
        page: Annotated[int, Field(description="Page number.")] = 1,
    ) -> dict:
        """Search Overseerr for movies, TV shows, and people across TMDB.

        ## Return Format
        {"success": bool, "message": str, "data": {results: [...]}}

        ## Examples
        overseerr_search(query="Dune")
        overseerr_search(query="The Expanse")
        """
        try:
            data = await client.search(query, page=page)
            total = len(data.get("results", []))
            return {"success": True, "message": f"Found {total} results for '{query}'", "data": data}
        except Exception as e:
            logger.exception("overseerr_search failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}

    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def overseerr_discover(
        media_type: Annotated[Literal["movie", "tv"], Field(description="Discover movies or TV series.")],
        sort_by: Annotated[str | None, Field(description="TMDB sort, for example popularity.desc or first_air_date.desc.")] = None,
        page: Annotated[int, Field(description="Result page number.")] = 1,
        watch_providers: Annotated[str | None, Field(description="TMDB watch-provider ID(s), comma-separated.")] = None,
        watch_region: Annotated[str | None, Field(description="Two-letter region for provider availability, such as US.")] = None,
        release_date_gte: Annotated[str | None, Field(description="Movie release-date lower bound, YYYY-MM-DD.")] = None,
        release_date_lte: Annotated[str | None, Field(description="Movie release-date upper bound, YYYY-MM-DD.")] = None,
        first_air_date_gte: Annotated[str | None, Field(description="TV first-air-date lower bound, YYYY-MM-DD.")] = None,
        first_air_date_lte: Annotated[str | None, Field(description="TV first-air-date upper bound, YYYY-MM-DD.")] = None,
        genre: Annotated[str | None, Field(description="TMDB genre ID(s), comma-separated.")] = None,
        language: Annotated[str | None, Field(description="Original language code, such as en.")] = None,
        network: Annotated[str | None, Field(description="TMDB network ID for TV discovery.")] = None,
        vote_average_gte: Annotated[str | None, Field(description="Minimum vote average.")] = None,
        vote_count_gte: Annotated[str | None, Field(description="Minimum vote count.")] = None,
    ) -> dict:
        """Discover movies or series using Seerr's web UI filters.

        This is read-only. Provider filtering is region-specific: supply the
        TMDB provider ID and watch_region rather than a provider name.
        Results are compacted for agent context and include Seerr/TMDB IDs
        plus whether an item is already known to Seerr.
        """
        try:
            if page < 1:
                return {"success": False, "message": "page must be at least 1", "data": {}}
            filters: dict[str, Any] = {
                "page": page,
                "sortBy": sort_by,
                "watchProviders": watch_providers,
                "watchRegion": watch_region,
                "primaryReleaseDateGte": release_date_gte if media_type == "movie" else None,
                "primaryReleaseDateLte": release_date_lte if media_type == "movie" else None,
                "firstAirDateGte": first_air_date_gte if media_type == "tv" else None,
                "firstAirDateLte": first_air_date_lte if media_type == "tv" else None,
                "genre": genre,
                "language": language,
                "network": network if media_type == "tv" else None,
                "voteAverageGte": vote_average_gte,
                "voteCountGte": vote_count_gte,
            }
            response = await client.discover(media_type, **filters)
            compact_results = []
            for item in response.get("results", []):
                compact_results.append({
                    "id": item.get("id"),
                    "tmdb_id": item.get("tmdbId", item.get("id")),
                    "title": item.get("title") or item.get("name"),
                    "media_type": item.get("mediaType", media_type),
                    "release_date": item.get("releaseDate") or item.get("primaryReleaseDate"),
                    "first_air_date": item.get("firstAirDate"),
                    "vote_average": item.get("voteAverage"),
                    "vote_count": item.get("voteCount"),
                    "popularity": item.get("popularity"),
                    "overview": item.get("overview"),
                    "status": item.get("status"),
                    "requested": bool(item.get("mediaInfo", {}).get("requests")) if isinstance(item.get("mediaInfo"), dict) else False,
                    "media_status": item.get("mediaInfo", {}).get("status") if isinstance(item.get("mediaInfo"), dict) else None,
                })
            data = {**{key: response.get(key) for key in ("page", "totalPages", "totalResults")}, "results": compact_results}
            return {"success": True, "message": f"Found {len(compact_results)} {media_type} discovery results", "data": data}
        except Exception as e:
            logger.exception("overseerr_discover failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}

    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def overseerr_movie_details(
        tmdb_id: Annotated[int, Field(description="TMDB movie ID.")],
        region: Annotated[str, Field(description="Two-letter release region, such as US.")] = "US",
    ) -> dict:
        """Return movie release dates from Seerr/TMDB for one region.

        Digital, physical, and TV dates are treated as broad availability.
        A theatrical date alone never marks a movie as downloadable.
        Missing digital data is reported as unknown rather than inferred.
        """
        try:
            if tmdb_id <= 0:
                return {"success": False, "message": "tmdb_id must be positive", "data": {}}
            region = region.upper()
            if len(region) != 2:
                return {"success": False, "message": "region must be a two-letter country code", "data": {}}
            details = await client.get_movie_details(tmdb_id)
            data = _release_summary(details, region)
            return {
                "success": True,
                "message": f"Release dates for {data.get('title') or tmdb_id} ({region})",
                "data": data,
            }
        except Exception as e:
            logger.exception("overseerr_movie_details failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}

    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False},
        version=TOOL_VERSION,
    )
    async def overseerr_users(
        operation: Annotated[
            Literal["list", "get", "requests"],
            Field(description="Operation: list users, get by ID, or view user's requests."),
        ],
        user_id: Annotated[int | None, Field(description="User ID for get/requests.")] = None,
        take: Annotated[int, Field(description="Results per page.")] = 20,
    ) -> dict:
        """Manage Overseerr users and their request history.

        ## Return Format
        {"success": bool, "message": str, "data": [...]}

        ## Examples
        overseerr_users(operation="list")
        overseerr_users(operation="requests", user_id=1)
        """
        try:
            if operation == "list":
                data = await client.get_users(take=take)
                return {"success": True, "message": f"Found {len(data.get('results', []))} users", "data": data}

            if operation == "get":
                if not user_id:
                    return {"success": False, "message": "user_id is required for get", "data": {}}
                data = await client.get_user(user_id)
                return {"success": True, "message": f"User {user_id}", "data": data}

            if operation == "requests":
                if not user_id:
                    return {"success": False, "message": "user_id is required for requests", "data": {}}
                data = await client.get_user_requests(user_id, take=take)
                return {"success": True, "message": f"Found requests for user {user_id}", "data": data}

            return {"success": False, "message": f"Unknown operation: {operation}", "data": {}}

        except Exception as e:
            logger.exception("overseerr_users failed: %s", e)
            return {"success": False, "message": str(e), "data": {}}
