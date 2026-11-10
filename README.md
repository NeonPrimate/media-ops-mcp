# Media Operations MCP

Put your media library in plain English.

Media Operations MCP connects an MCP-compatible agent to self-hosted movie and TV services so people can search, inspect, organize, and manage a media library through natural language instead of juggling several administration panels.

This repository contains the public, sanitized backend package used by the Hermes Media Operations plugin as its first integration. The plugin handles connection and verification in Hermes Desktop; this server provides the tools that talk to Radarr, Sonarr, and the surrounding media services.

## What it can connect

- Radarr — movies
- Sonarr — TV series and episodes
- Lidarr — music
- Prowlarr — indexers
- Readarr — books (upstream service support may vary)
- Overseerr — requests and discovery
- Bazarr — subtitles
- Optional Jellyfin, Plex, and Emby bridge checks
- qBittorrent download status and operations

Availability depends on which services a user configures. Unconfigured services are skipped.

## Human-directed operation

The agent can explain choices before a consequential action. For example:

- “What movies are already available?”
- “Find the best releases for this film and explain the tradeoffs.”
- “Why is this episode missing?”
- “Show me what is downloading.”
- “Add this series, but ask me before grabbing anything.”

The MCP server does not contain credentials or a private deployment configuration. Users provide their own service URLs and credentials locally through environment variables or the service settings UI.

## Quick start

Requires Python 3.12+ and `uv`.

```bash
uv sync
cp .env.example .env
# Edit .env with your own local service URLs and API keys.
uv run arr-mcp
```

For an HTTP MCP endpoint:

```bash
ARR_MCP_TRANSPORT=http uv run arr-mcp
```

See [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) for configuration and [`docs/TOOLS.md`](docs/TOOLS.md) for the available tool families.

## Hermes integration

Install or open the companion plugin:

<https://github.com/NeonPrimate/hermes-media-ops>

The plugin provides a connection page, a read-only health check, and explicit registration of the remote MCP endpoint with Hermes. It does not silently change media, download files, or mutate infrastructure.

## Project relationship and attribution

This public repository is a sanitized distribution of the Media Operations MCP implementation and retains the upstream project’s MIT license and attribution. Private deployment files, credentials, machine addresses, logs, and local media inventories are intentionally excluded.

## License

MIT. See [`LICENSE`](LICENSE).
