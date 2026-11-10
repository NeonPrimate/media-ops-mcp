"""Tests for the safe Sonarr release MCP tools."""

from __future__ import annotations

import json

import httpx
import pytest

from arr_mcp.services.sonarr_service import SonarrClient
from arr_mcp.tools.sonarr_tools import register_sonarr_tools
from tests.conftest import MockMCP

SONARR_URL = "http://localhost:8989"
API_KEY = "test-api-key"


def _release(*, approved: bool = True, rejected: bool = False) -> dict:
    return {
        "guid": "magnet:?xt=urn:btih:example",
        "quality": {"quality": {"name": "WEBDL-1080p"}},
        "size": 123456789,
        "indexer": "Jackett",
        "releaseGroup": "MeGusta",
        "title": "Crystal Lake S01E04 1080p HEVC x265-MeGusta",
        "mappedEpisodeInfo": [{"id": 4504, "seasonNumber": 1, "episodeNumber": 4}],
        "approved": approved,
        "temporarilyRejected": False,
        "rejected": rejected,
        "downloadAllowed": True,
        "rejections": ["too large"] if rejected else [],
        "protocol": "torrent",
        "seeders": 42,
    }


def _callback(release: dict, requests: list[httpx.Request]):
    def callback(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(200, json=[release])
        return httpx.Response(200, json={"accepted": True})

    return callback


@pytest.mark.asyncio
async def test_release_search_returns_compact_candidate_without_magnet(httpx_mock) -> None:
    requests: list[httpx.Request] = []
    httpx_mock.add_callback(_callback(_release(), requests), is_reusable=True)
    client = SonarrClient(SONARR_URL, API_KEY)
    mcp = MockMCP()
    register_sonarr_tools(mcp, client)

    try:
        result = await mcp.tools["sonarr_release_search"](episode_id=4504)
    finally:
        await client.close()

    assert result["success"] is True
    candidate = result["data"][0]
    assert candidate["title"].endswith("MeGusta")
    assert candidate["eligible"] is True
    assert "candidate_id" in candidate
    assert "guid" not in candidate
    assert "magnet" not in json.dumps(result).lower()
    assert "episodeId=4504" in str(requests[0].url)


@pytest.mark.asyncio
async def test_release_grab_refetches_and_posts_only_eligible_exact_release(httpx_mock) -> None:
    requests: list[httpx.Request] = []
    release = _release()
    httpx_mock.add_callback(_callback(release, requests), is_reusable=True)
    client = SonarrClient(SONARR_URL, API_KEY)
    mcp = MockMCP()
    register_sonarr_tools(mcp, client)
    candidate_id = "c"  # replaced with the real opaque ID below
    from arr_mcp.tools.sonarr_tools import _candidate_id

    candidate_id = _candidate_id(release)
    try:
        result = await mcp.tools["sonarr_release_grab"](episode_id=4504, candidate_id=candidate_id)
    finally:
        await client.close()

    assert result["success"] is True
    assert len(requests) == 2
    assert requests[1].method == "POST"
    assert json.loads(requests[1].content) == release


@pytest.mark.asyncio
async def test_release_grab_refuses_rejected_release_without_post(httpx_mock) -> None:
    requests: list[httpx.Request] = []
    release = _release(approved=False, rejected=True)
    httpx_mock.add_callback(_callback(release, requests), is_reusable=True)
    client = SonarrClient(SONARR_URL, API_KEY)
    mcp = MockMCP()
    register_sonarr_tools(mcp, client)
    from arr_mcp.tools.sonarr_tools import _candidate_id

    try:
        result = await mcp.tools["sonarr_release_grab"](
            episode_id=4504, candidate_id=_candidate_id(release)
        )
    finally:
        await client.close()

    assert result["success"] is False
    assert "safety checks" in result["message"]
    assert len(requests) == 1
