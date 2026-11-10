"""Tests for Seerr/TMDB-backed discovery."""

from __future__ import annotations

from arr_mcp.services.overseerr_service import OverseerrClient
from arr_mcp.tools.overseerr_tools import register_overseerr_tools
from tests.conftest import MockMCP

SEERR_URL = "http://seerr:5055"
API_KEY = "test-api-key"


async def test_discover_service_uses_seerr_filter_names(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=(
            f"{SEERR_URL}/api/v1/discover/tv?"
            "page=1&sortBy=popularity.desc&watchProviders=8&watchRegion=US&firstAirDateLte=2026-11-08"
        ),
        json={"page": 1, "totalPages": 1, "totalResults": 1, "results": []},
    )
    client = OverseerrClient(SEERR_URL, API_KEY)
    try:
        result = await client.discover(
            "tv",
            page=1,
            sortBy="popularity.desc",
            watchProviders="8",
            watchRegion="US",
            firstAirDateLte="2026-11-08",
        )
    finally:
        await client.close()
    assert result["totalResults"] == 1


class FakeDiscoverClient:
    async def discover(self, media_type: str, **filters):
        assert media_type == "tv"
        assert filters["watchProviders"] == "8"
        return {
            "page": 1,
            "totalPages": 1,
            "totalResults": 1,
            "results": [
                {
                    "id": 123,
                    "name": "Example Show",
                    "firstAirDate": "2026-11-01",
                    "voteAverage": 8.2,
                    "voteCount": 100,
                    "popularity": 42.0,
                    "overview": "A test show.",
                    "mediaInfo": {"requests": [{"id": 4}], "status": 2},
                    "downloadUrl": "must-not-be-returned",
                }
            ],
        }


import pytest


@pytest.mark.asyncio
async def test_discover_tool_compacts_results_and_marks_requested():
    mcp = MockMCP()
    register_overseerr_tools(mcp, FakeDiscoverClient())
    result = await mcp.tools["overseerr_discover"](
        media_type="tv",
        sort_by="popularity.desc",
        watch_providers="8",
        watch_region="US",
        first_air_date_lte="2026-11-08",
    )
    assert result["success"] is True
    item = result["data"]["results"][0]
    assert item["title"] == "Example Show"
    assert item["requested"] is True
    assert "downloadUrl" not in str(result)


async def test_movie_details_uses_full_release_dates(httpx_mock):
    httpx_mock.add_response(
        method="GET",
        url=f"{SEERR_URL}/api/v1/movie/372",
        json={
            "id": 372,
            "title": "Musk",
            "status": "Released",
            "overview": "A test movie.",
            "releases": {
                "results": [
                    {
                        "iso_3166_1": "US",
                        "release_dates": [
                            {"release_date": "2026-11-06T00:00:00.000Z", "type": 4},
                            {"release_date": "2026-10-01T00:00:00.000Z", "type": 3},
                        ],
                    }
                ]
            },
        },
    )
    client = OverseerrClient(SEERR_URL, API_KEY)
    try:
        details = await client.get_movie_details(372)
    finally:
        await client.close()
    assert details["releases"]["results"][0]["iso_3166_1"] == "US"


class FakeMovieDetailsClient:
    async def get_movie_details(self, tmdb_id: int):
        assert tmdb_id == 372
        return {
            "id": 372,
            "title": "Musk",
            "status": "Released",
            "releases": {
                "results": [
                    {
                        "iso_3166_1": "US",
                        "release_dates": [
                            {"release_date": "2026-11-06T00:00:00.000Z", "type": 4},
                            {"release_date": "2026-10-01T00:00:00.000Z", "type": 3},
                        ],
                    }
                ]
            },
        }


import pytest


@pytest.mark.asyncio
async def test_movie_details_distinguishes_digital_from_theatrical():
    mcp = MockMCP()
    register_overseerr_tools(mcp, FakeMovieDetailsClient())
    result = await mcp.tools["overseerr_movie_details"](tmdb_id=372, region="us")
    assert result["success"] is True
    assert result["data"]["digital_release"] == "2026-11-06"
    assert result["data"]["theatrical_release"] == "2026-10-01"
    assert result["data"]["availability_status"] == "released"
