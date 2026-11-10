"""Tests for deterministic Radarr release recommendations."""

from __future__ import annotations

import pytest

from arr_mcp.tools.radarr_tools import _recommend_releases, register_radarr_tools
from tests.conftest import MockMCP


def candidate(title: str, *, seeders: int, quality: str = "Bluray-1080p", candidate_id: str) -> dict:
    return {
        "candidate_id": candidate_id,
        "title": title,
        "indexer": "Jackett - Torrent Downloads",
        "release_group": None,
        "quality": quality,
        "size": 1_440_000_000,
        "seeders": seeders,
        "protocol": "torrent",
        "approved": True,
        "rejected": False,
        "temporarily_rejected": False,
        "download_allowed": True,
        "rejections": [],
        "eligible": True,
    }


def test_recommendations_deduplicate_and_prefer_more_seeders() -> None:
    result = _recommend_releases(
        [
            candidate("Easy Rider 1969 Criterion 1080p BluRay HEVC x265 BONE", seeders=98, candidate_id="low"),
            candidate("Easy.Rider.1969.Criterion.1080p.BluRay.HEVC.x265.BONE", seeders=120, candidate_id="high"),
            candidate("Easy Rider 1969 HDTV 1080p", seeders=200, quality="HDTV-1080p", candidate_id="hdtv"),
        ],
        4,
    )

    assert result["eligible_count"] == 3
    assert result["deduplicated_count"] == 2
    assert result["recommendations"][0]["candidate_id"] == "high"
    assert "Criterion source" in result["recommendations"][0]["reasons"]


def test_recommendations_prioritize_availability_and_compact_size() -> None:
    result = _recommend_releases(
        [
            candidate("Dog Day Afternoon 1975 1080p BluRay x265 Remaster", seeders=7, candidate_id="large"),
            candidate("Dog Day Afternoon 1975 1080p BRRip x264 YTS", seeders=100, candidate_id="compact"),
        ],
        2,
    )

    assert result["recommendations"][0]["candidate_id"] == "compact"
    assert "compact YTS/YIFY encode; expect more compression" in result["recommendations"][0]["reasons"]
    assert "availability risk: fewer than 10 seeders" in result["recommendations"][1]["reasons"]


class FakeRadarr:
    async def get_release_candidates(self, movie_id: int) -> list[dict]:
        assert movie_id == 378
        return [
            {
                "guid": "guid-best",
                "mappedMovieId": 378,
                "title": "Easy Rider 1969 Criterion 1080p BluRay HEVC x265 BONE",
                "indexer": "Jackett - Torrent Downloads",
                "quality": {"quality": {"name": "Bluray-1080p"}},
                "size": 1_440_000_000,
                "seeders": 120,
                "protocol": "torrent",
                "approved": True,
                "rejected": False,
                "temporarilyRejected": False,
                "downloadAllowed": True,
                "rejections": [],
            },
        ]


@pytest.mark.asyncio
async def test_recommender_is_read_only_and_limits_options() -> None:
    mcp = MockMCP()
    register_radarr_tools(mcp, FakeRadarr())

    result = await mcp.tools["radarr_release_recommend"](movie_id=378, limit=1)

    assert result["success"] is True
    assert result["data"]["recommendations"][0]["candidate_id"] == "best"
    assert len(result["data"]["recommendations"]) == 1
    assert "radarr_release_grab" not in result["message"]
