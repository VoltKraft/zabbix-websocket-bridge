# zabbix-websocket-bridge

`zabbix-websocket-bridge` is a generic, stateless HTTP-to-WebSocket JSON-RPC bridge for monitoring and automation systems that can send HTTP JSON requests but need to reach a JSON-RPC endpoint exposed over WebSocket.

The project contains no vendor-specific behavior, no target-specific configuration, no credential storage, no sessions, no database, and no cache. Every request provides the complete WebSocket target and the JSON-RPC calls to execute. The bridge is a translator for trusted clients on a shared Docker network: it has no authentication, destination allowlist, or RPC method policy. The included Compose configuration publishes no host port.

## Architecture overview

```text
HTTP JSON Request
        ↓
zabbix-websocket-bridge
        ↓
WebSocket JSON-RPC
        ↓
Target System

Target System Response
        ↓
zabbix-websocket-bridge
        ↓
HTTP JSON Response
```

For each batch request the bridge opens one WebSocket connection, sends the JSON-RPC calls sequentially, correlates responses by JSON-RPC `id`, returns one aggregated HTTP JSON response, and closes the WebSocket connection.

## API specification

### Health

```http
GET /health
```

Response:

```json
{
  "status": "ok"
}
```

### Batch JSON-RPC

```http
POST /api/v1/jsonrpc/batch
Content-Type: application/json
```

Request:

```json
{
  "target": {
    "url": "wss://example.local/ws",
    "verify_tls": true
  },
  "calls": [
    {
      "name": "example_call",
      "method": "example.method",
      "params": []
    }
  ],
  "timeout": 10
}
```

Validation rules:

- `target.url` must use `ws://` or `wss://` and contain a valid host and port. Its length is limited to 2048 characters; fragments, whitespace, and control characters are rejected. Destinations and methods require no server-side registration.
- `target.verify_tls` is optional and defaults to `true`.
- `calls` must contain at least one call and at most 50 calls.
- `timeout` is optional, defaults to 10 seconds, and may not exceed 60 seconds.
- Unknown fields are rejected.
- Bodies are limited to 128 KiB (including streamed/chunked requests), UTF-8, and 32 levels of JSON nesting before parsing. Body reception must finish within 10 seconds.
- JSON params are limited to 8192 aggregate nodes and 2048 items per collection. Serialized RPC messages are limited to 64 KiB each and 128 KiB per batch. Only finite JSON numbers are accepted.
- Target responses are limited to 64 KiB per WebSocket message and 1 MiB per batch; WebSocket compression is disabled.

Successful response:

```json
{
  "ok": true,
  "results": {
    "example_call": {
      "ok": true,
      "result": {}
    }
  },
  "errors": []
}
```

Individual call failure response:

```json
{
  "ok": true,
  "results": {
    "call_a": {
      "ok": true,
      "result": {}
    },
    "call_b": {
      "ok": false,
      "error": "Remote error message"
    }
  },
  "errors": []
}
```

Connection-level failures return HTTP `502` with a global error payload in the response detail. Oversized bodies return `413`, invalid batches `422`, and slow body reception `408`. Excess concurrency is rejected immediately with `503` and `Retry-After: 1`; requests are not queued.

## Container installation

The container image is distributed through GitHub Container Registry (GHCR) only.
Use the published GHCR image for installations and deployments instead of building a local deployment image.

Image:

```text
ghcr.io/voltkraft/zabbix-websocket-bridge
```

Pull and run the latest image on your existing `monitoring` Docker network (replace the network name as needed):

```sh
docker pull ghcr.io/voltkraft/zabbix-websocket-bridge:latest
docker run --rm --name zabbix-websocket-bridge \
  --network monitoring \
  --memory=256m --cpus=1 --pids-limit=64 --ulimit nofile=1024:1024 \
  ghcr.io/voltkraft/zabbix-websocket-bridge:latest
```

The container listens on port `8080` by default. Runtime configuration is controlled through environment variables:

- `HOST`: bind address inside the container, defaults to `0.0.0.0`.
- `PORT`: HTTP port inside the container, defaults to `8080`.
- `LOG_LEVEL`: Uvicorn log level, defaults to `info`.
- `BRIDGE_MAX_CONCURRENT_BATCHES`: requests admitted per process, defaults to `8` (range 1–128), including body reception and response sending. The supplied runner uses one worker, a 64-connection server limit, a backlog of 64, and a five-second keep-alive timeout. Multiple workers/replicas multiply these limits.

## Docker Compose examples

The included `compose.yaml` keeps the bridge reachable on its Docker network without publishing a host port:

```yaml
services:
  zabbix-websocket-bridge:
    image: ghcr.io/voltkraft/zabbix-websocket-bridge:latest
    pull_policy: always
    environment:
      HOST: 0.0.0.0
      PORT: 8080
      LOG_LEVEL: info
      BRIDGE_MAX_CONCURRENT_BATCHES: 8
    expose:
      - "8080"
    mem_limit: 256m
    cpus: 1.0
    pids_limit: 64
    ulimits:
      nofile:
        soft: 1024
        hard: 1024
    restart: unless-stopped
```

Start a Compose deployment:

```sh
docker compose up -d
```

Clients in the same Compose network can reach `http://zabbix-websocket-bridge:8080`. To connect a client from another Compose project, attach both services to the same existing Docker network. `expose` documents the container port; it does not publish it on the host or restrict outbound connections to target systems.

No token, policy file, or target registration is required. The network boundary is the intended access control. The resource limits described here require an image built from this revision or later.

## Example curl requests

Run these from a client container on the shared Docker network. For local development, use `localhost` instead of the service name.

Health check:

```sh
curl http://zabbix-websocket-bridge:8080/health
```

Batch JSON-RPC request:

```sh
curl -X POST http://zabbix-websocket-bridge:8080/api/v1/jsonrpc/batch \
  -H 'Content-Type: application/json' \
  -d '{
    "target": {
      "url": "wss://example.local/ws",
      "verify_tls": true
    },
    "calls": [
      {
        "name": "example_call",
        "method": "example.method",
        "params": []
      }
    ],
    "timeout": 10
  }'
```

## Development instructions

Create a virtual environment and install development dependencies:

```sh
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Run the API locally:

```sh
HOST=127.0.0.1 PORT=8080 LOG_LEVEL=info python -m zabbix_websocket_bridge.main
```

Run tests:

```sh
pytest
```

## Container build automation

The `Container Image` workflow (`.github/workflows/container-image.yaml`) builds the GHCR image automatically on:

- Pushes to `main`.
- Version tags matching `v*`.
- Manual `workflow_dispatch` runs.
- Weekly scheduled rebuilds.

Scheduled and manual rebuilds pull the current base image and bypass the build cache, so base image and Python dependency updates are picked up even when the repository did not change.

The workflow first builds a local candidate image and compares it with the currently published `ghcr.io/voltkraft/zabbix-websocket-bridge:latest` image. If the candidate is identical to the latest published image, nothing is pushed. If it differs, the candidate is tagged and published to GHCR.

Published tags include `latest`, branch names, semantic version tags, and commit SHA tags.

## Dependency updates

[Dependabot](.github/dependabot.yml) checks Python dependencies, GitHub Actions,
and the Docker base image every Monday starting at 07:00 Europe/Berlin.
Python runtime and development/build minor and patch updates are grouped
separately; GitHub Actions minor and patch updates form another group. Major
version updates remain individual PRs. Version updates have a three-day release
cooldown and a limit of five open PRs per ecosystem (two for Docker).

Python updates use `versioning-strategy: increase` to raise the minimum versions
in `pyproject.toml`, including when a newer release already fits an open range.
Security updates are grouped separately for Python and GitHub Actions and do
not wait for the weekly schedule or version-update cooldown. GitHub's dependency
graph, Dependabot alerts, and Dependabot security updates must be enabled in the
repository's **Settings → Advanced Security**; the YAML file alone does not
enable those repository settings. The configuration takes effect when it reaches
the default branch. See the [GitHub configuration reference](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference)
and [security update setup](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/configure-security-updates).

The rolling `python:3-slim` tag and unpinned Python installation remain intentional:
scheduled image rebuilds still pick up current releases within the declared
constraints. Dependabot's PR cooldown does not delay those installations. Docker
updates cover changes to the base-image tag; refreshing the contents of the same
tag is handled by the container workflow. Compose uses this project's own
`:latest` image, so it has no separate Dependabot entry. There is no Python lock
file; the manifest does not record the exact transitive packages installed in a
published image, so Dependabot is not a complete inventory or vulnerability scan
of that image.

The [CI workflow](.github/workflows/ci.yaml) checks every PR (including Dependabot
PRs) with the test suite on Python 3.13 and the latest stable Python 3, `pip check`,
and a container build and health check. It uses read-only repository permissions
and does not publish images or require registry secrets. Updates require manual
review and merge; automatic merging is not configured. Maintainers can make the
CI jobs required checks in branch protection.

## Security considerations

- The bridge deliberately does not authenticate callers or restrict target addresses or RPC methods. Access is controlled by the shared trusted Docker network; the included Compose deployment publishes no host port.
- The authentication and arbitrary-target scan findings represent this intended trust model; they are not claimed as fixed in application code. The body-size and concurrent-request findings are addressed with application resource limits.
- Keep the container resource limits and configure `BRIDGE_MAX_CONCURRENT_BATCHES` for the available capacity. `/health` reports process liveness.
- The bridge does not store credentials, sessions, target definitions, request payloads, responses, or cached data.
- Operational target logs include only the origin, not URL credentials, paths, or query strings. Avoid debug protocol logging when payloads contain credentials.
- If credentials are embedded in a WebSocket URL, they are used only for the outbound connection and are removed from operational log messages.
- TLS verification is enabled by default for `wss://` targets. Disable it only for controlled development or test environments.
- The container runs as a non-root user.

## License

This project is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.
