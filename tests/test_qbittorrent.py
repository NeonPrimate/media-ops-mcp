"""Tests for the read-only qBittorrent client."""

import pytest

from arr_mcp.services.qbittorrent_service import QBittorrentClient

URL = "https://qbit.example.test"


@pytest.mark.asyncio
async def test_api_key_auth_and_list_torrents(httpx_mock):
    httpx_mock.add_response(url=f"{URL}/api/v2/app/version", text="v5.1.0", is_reusable=True)
    httpx_mock.add_response(
        url=f"{URL}/api/v2/torrents/info?filter=completed&category=tv",
        json=[{"hash": "abc", "name": "Episode", "progress": 1}],
    )
    client = QBittorrentClient(URL, api_key="test-key")
    try:
        assert await client.get_version() == "v5.1.0"
        torrents = await client.get_torrents(state_filter="completed", category="tv")
        assert torrents[0]["hash"] == "abc"
        assert httpx_mock.get_requests()[0].headers["X-Api-Key"] == "test-key"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_username_password_fallback(httpx_mock):
    httpx_mock.add_response(url=f"{URL}/api/v2/auth/login", method="POST", status_code=204)
    httpx_mock.add_response(url=f"{URL}/api/v2/app/version", text="v4.6.7")
    client = QBittorrentClient(URL, username="user", password="pass")
    try:
        assert await client.get_version() == "v4.6.7"
        assert httpx_mock.get_requests()[0].url.path == "/api/v2/auth/login"
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_torrent_details_and_files(httpx_mock):
    httpx_mock.add_response(url=f"{URL}/api/v2/app/version", text="v5.1.0")
    httpx_mock.add_response(
        url=f"{URL}/api/v2/torrents/properties?hash=abc",
        json={"save_path": "/downloads/tv", "state": "uploading"},
    )
    httpx_mock.add_response(
        url=f"{URL}/api/v2/torrents/files?hash=abc",
        json=[{"name": "Episode.mkv", "progress": 1}],
    )
    client = QBittorrentClient(URL, api_key="test-key")
    try:
        assert (await client.get_torrent("abc"))["save_path"] == "/downloads/tv"
        assert (await client.get_torrent_files("abc"))[0]["name"] == "Episode.mkv"
    finally:
        await client.close()
