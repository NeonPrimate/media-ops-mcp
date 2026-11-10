"""Read-only qBittorrent MCP tools."""

from __future__ import annotations

import logging
from typing import Annotated, Literal

from pydantic import Field

from arr_mcp.constants import TOOL_VERSION
from arr_mcp.services.qbittorrent_service import QBittorrentClient

logger = logging.getLogger(__name__)


def _compact_torrent(torrent: dict) -> dict:
    """Keep list results useful to an agent without leaking tracker payloads."""
    fields = (
        "hash",
        "name",
        "state",
        "progress",
        "amount_left",
        "size",
        "dlspeed",
        "upspeed",
        "eta",
        "ratio",
        "category",
        "tags",
        "save_path",
        "content_path",
        "root_path",
    )
    return {key: torrent[key] for key in fields if key in torrent}


def register_qbittorrent_tools(mcp, client: QBittorrentClient | None) -> None:
    """Register safe qBittorrent inspection tools."""

    def unavailable() -> dict:
        return {"success": False, "message": "qBittorrent is not configured."}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False}, version=TOOL_VERSION)
    async def qbittorrent_health() -> dict:
        """Check qBittorrent reachability and report its version."""
        if client is None:
            return unavailable()
        try:
            return {"success": True, "data": await client.health_check()}
        except Exception as exc:
            logger.warning("qBittorrent health check failed: %s", exc)
            return {"success": False, "message": str(exc)}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False}, version=TOOL_VERSION)
    async def qbittorrent_list_torrents(
        state_filter: Annotated[
            Literal["all", "downloading", "seeding", "completed", "paused", "active", "inactive", "stalled", "errored"],
            Field(description="Optional qBittorrent state filter."),
        ] = "all",
        category: Annotated[str | None, Field(description="Optional qBittorrent category.")] = None,
    ) -> dict:
        """List torrents and their current states without changing anything."""
        if client is None:
            return unavailable()
        try:
            items = await client.get_torrents(state_filter=None if state_filter == "all" else state_filter, category=category)
            return {"success": True, "count": len(items), "data": [_compact_torrent(item) for item in items]}
        except Exception as exc:
            logger.warning("qBittorrent torrent listing failed: %s", exc)
            return {"success": False, "message": str(exc)}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False}, version=TOOL_VERSION)
    async def qbittorrent_get_torrent(
        torrent_hash: Annotated[str, Field(description="Torrent hash from qbittorrent_list_torrents.")],
        include_files: Annotated[bool, Field(description="Include the torrent's file list.")] = False,
    ) -> dict:
        """Get torrent properties, save path, and optionally its files."""
        if client is None:
            return unavailable()
        try:
            data = await client.get_torrent(torrent_hash)
            if include_files:
                data["files"] = await client.get_torrent_files(torrent_hash)
            return {"success": True, "data": data}
        except Exception as exc:
            logger.warning("qBittorrent torrent lookup failed: %s", exc)
            return {"success": False, "message": str(exc)}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False}, version=TOOL_VERSION)
    async def qbittorrent_transfer_info() -> dict:
        """Get global qBittorrent transfer speeds and limits."""
        if client is None:
            return unavailable()
        try:
            return {"success": True, "data": await client.get_transfer_info()}
        except Exception as exc:
            logger.warning("qBittorrent transfer info failed: %s", exc)
            return {"success": False, "message": str(exc)}
