"""Tests for Sonarr interactive release operations."""

from __future__ import annotations

import json

import pytest

from arr_mcp.services.sonarr_service import SonarrClient

SONARR_URL = "http://localhost:8989"
API_KEY = "test-api-key"


@pytest.mark.asyncio
async def test_get_release_candidates_uses_episode_and_query_api_key(httpx_mock) -> None:
    client = SonarrClient(SONARR_URL, API_KEY)
    response = [{"title": "Example S01E04 1080p HEVC", "indexerId": 1}]
    httpx_mock.add_response(
        method="GET",
        url=f"{SONARR_URL}/api/v3/release?episodeId=4504&apikey={API_KEY}",
        json=response,
    )

    try:
        assert await client.get_release_candidates(4504) == response
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_grab_release_posts_exact_release_object_with_query_api_key(httpx_mock) -> None:
    client = SonarrClient(SONARR_URL, API_KEY)
    release = {
        "guid": "candidate-guid",
        "indexerId": 1,
        "title": "Example S01E04 1080p HEVC",
        "episodeIds": [4504],
        "approved": True,
        "rejected": False,
        "temporarilyRejected": False,
        "downloadAllowed": True,
        "protocol": "torrent",
    }
    httpx_mock.add_response(
        method="POST",
        url=f"{SONARR_URL}/api/v3/release?apikey={API_KEY}",
        json={"accepted": True},
    )

    try:
        assert await client.grab_release(release) == {"accepted": True}
    finally:
        await client.close()

    request = httpx_mock.get_requests()[0]
    assert json.loads(request.content) == release
