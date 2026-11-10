"""Tests for Radarr interactive release operations."""

from __future__ import annotations

import json

import httpx
import pytest

from arr_mcp.services.radarr_service import RadarrClient
from arr_mcp.tools.radarr_tools import _candidate_id, register_radarr_tools
from tests.conftest import MockMCP

RADARR_URL = "http://localhost:7878"
API_KEY = "test-api-key"


def release(*, approved: bool = True, rejected: bool = False) -> dict:
    return {
        "guid": "https://example.invalid/release/one",
        "quality": {"quality": {"name": "WEBDL-1080p"}},
        "size": 2_136_746_229,
        "indexer": "Jackett - LimeTorrents",
        "releaseGroup": "BONE",
        "title": "Musk 2026 1080p WEB DL HEVC x265 5 1 BONE",
        "mappedMovieId": 372,
        "approved": approved,
        "temporarilyRejected": False,
        "rejected": rejected,
        "downloadAllowed": True,
        "rejections": ["too large"] if rejected else [],
        "protocol": "torrent",
        "seeders": 1617,
    }


def callback(candidate: dict, requests: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[candidate])
        return httpx.Response(200, json={"accepted": True})

    return handle


@pytest.mark.asyncio
async def test_radarr_client_release_methods_use_movie_id_and_query_key(httpx_mock) -> None:
    client = RadarrClient(RADARR_URL, API_KEY)
    candidate = release()
    httpx_mock.add_response(
        method="GET",
        url=f"{RADARR_URL}/api/v3/release?movieId=372&apikey={API_KEY}",
        json=[candidate],
    )
    httpx_mock.add_response(
        method="POST",
        url=f"{RADARR_URL}/api/v3/release?apikey={API_KEY}",
        json={"accepted": True},
    )

    try:
        assert await client.get_release_candidates(372) == [candidate]
        assert await client.grab_release(candidate) == {"accepted": True}
    finally:
        await client.close()

    assert json.loads(httpx_mock.get_requests()[1].content) == candidate


@pytest.mark.asyncio
async def test_radarr_release_search_is_compact_and_redacted(httpx_mock) -> None:
    candidate = release()
    requests: list[httpx.Request] = []
    httpx_mock.add_callback(callback(candidate, requests), is_reusable=True)
    client = RadarrClient(RADARR_URL, API_KEY)
    mcp = MockMCP()
    register_radarr_tools(mcp, client)

    try:
        result = await mcp.tools["radarr_release_search"](movie_id=372)
    finally:
        await client.close()

    assert result["success"] is True
    assert result["data"][0]["eligible"] is True
    assert result["data"][0]["candidate_id"] == _candidate_id(candidate)
    assert "guid" not in json.dumps(result)


@pytest.mark.asyncio
async def test_radarr_release_grab_refuses_rejected_release_before_post(httpx_mock) -> None:
    candidate = release(approved=False, rejected=True)
    requests: list[httpx.Request] = []
    httpx_mock.add_callback(callback(candidate, requests), is_reusable=True)
    client = RadarrClient(RADARR_URL, API_KEY)
    mcp = MockMCP()
    register_radarr_tools(mcp, client)

    try:
        result = await mcp.tools["radarr_release_grab"](
            movie_id=372, candidate_id=_candidate_id(candidate)
        )
    finally:
        await client.close()

    assert result["success"] is False
    assert "safety checks" in result["message"]
    assert len(requests) == 1
