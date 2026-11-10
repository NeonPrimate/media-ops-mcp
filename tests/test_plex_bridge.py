"""Tests for Plex bridge cross-arr orchestration."""

import pytest

from arr_mcp.constants import MediaType
from arr_mcp.utils.plex_bridge import PlexBridge


class TestPlexBridge:
    def test_not_configured_by_default(self):
        bridge = PlexBridge("", "")
        assert not bridge.is_configured

    def test_configured_with_url_and_token(self):
        bridge = PlexBridge("http://localhost:32400", "test-token")
        assert bridge.is_configured

    @pytest.mark.asyncio
    async def test_search_not_configured(self):
        bridge = PlexBridge("", "")
        results = await bridge.search("Dune")
        assert results == []

    @pytest.mark.asyncio
    async def test_check_availability_not_configured(self):
        bridge = PlexBridge("", "")
        result = await bridge.check_availability("Dune")
        assert result["in_library"] is False
        assert result["note"] == "Plex not configured"

    @pytest.mark.asyncio
    async def test_search_returns_items(self, httpx_mock):
        httpx_mock.add_response(
            url="http://localhost:32400/search?query=Dune&limit=10",
            json={
                "MediaContainer": {
                    "Video": [
                        {"ratingKey": "abc123", "title": "Dune", "type": "movie", "year": 2021},
                    ],
                },
            },
        )
        bridge = PlexBridge("http://localhost:32400", "test-token")
        results = await bridge.search("Dune")
        assert len(results) == 1
        assert results[0]["title"] == "Dune"
        await bridge.close()

    @pytest.mark.asyncio
    async def test_find_title_exists(self, httpx_mock):
        httpx_mock.add_response(
            url="http://localhost:32400/search?query=Dune&limit=10",
            json={
                "MediaContainer": {
                    "Video": [
                        {"ratingKey": "abc123", "title": "Dune", "type": "movie", "year": 2021},
                    ],
                },
            },
        )
        bridge = PlexBridge("http://localhost:32400", "test-token")
        item = await bridge.find_title("Dune", MediaType.MOVIE)
        assert item is not None
        assert item["title"] == "Dune"
        await bridge.close()

    @pytest.mark.asyncio
    async def test_find_title_not_found(self, httpx_mock):
        httpx_mock.add_response(
            url="http://localhost:32400/search?query=NonExistent&limit=10",
            json={"MediaContainer": {}},
        )
        bridge = PlexBridge("http://localhost:32400", "test-token")
        item = await bridge.find_title("NonExistent")
        assert item is None
        await bridge.close()

    @pytest.mark.asyncio
    async def test_check_availability_found(self, httpx_mock):
        httpx_mock.add_response(
            url="http://localhost:32400/search?query=Inception&limit=10",
            json={
                "MediaContainer": {
                    "Video": [
                        {"ratingKey": "xyz789", "title": "Inception", "type": "movie", "year": 2010},
                    ],
                },
            },
        )
        bridge = PlexBridge("http://localhost:32400", "test-token")
        result = await bridge.check_availability("Inception", MediaType.MOVIE)
        assert result["in_library"] is True
        assert result["matched_title"] == "Inception"
        assert result["plex_rating_key"] == "xyz789"
        await bridge.close()
