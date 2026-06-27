# zabbix-websocket-bridge

`zabbix-websocket-bridge` is a generic, stateless HTTP-to-WebSocket JSON-RPC bridge for monitoring and automation systems that can send HTTP JSON requests but need to reach a JSON-RPC endpoint exposed over WebSocket.

The project contains no vendor-specific behavior, no target-specific configuration, no credential storage, no sessions, no database, and no cache. Every request provides the complete WebSocket target and the JSON-RPC calls to execute.

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

- `target.url` must use `ws://` or `wss://`.
- `target.verify_tls` is optional and defaults to `true`.
- `calls` must contain at least one call and at most 50 calls.
- `timeout` is optional, defaults to 10 seconds, and may not exceed 60 seconds.
- Unknown fields are rejected.

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

Connection-level failures return HTTP `502` with a global error payload in the response detail.

## Container installation

The container image is distributed through GitHub Container Registry (GHCR) only.
Use the published GHCR image for installations and deployments instead of building a local deployment image.

Image:

```text
ghcr.io/voltkraft/zabbix-websocket-bridge
```

Pull and run the latest image:

```sh
docker pull ghcr.io/voltkraft/zabbix-websocket-bridge:latest
docker run --rm --name zabbix-websocket-bridge -p 8080:8080 ghcr.io/voltkraft/zabbix-websocket-bridge:latest
```

The container listens on port `8080` by default. Runtime configuration is controlled through environment variables:

- `HOST`: bind address inside the container, defaults to `0.0.0.0`.
- `PORT`: HTTP port inside the container, defaults to `8080`.
- `LOG_LEVEL`: Uvicorn log level, defaults to `info`.

## Docker Compose examples

Basic `compose.yaml`:

```yaml
services:
  zabbix-websocket-bridge:
    image: ghcr.io/voltkraft/zabbix-websocket-bridge:latest
    pull_policy: always
    environment:
      HOST: 0.0.0.0
      PORT: 8080
      LOG_LEVEL: info
    ports:
      - "8080:8080"
    restart: unless-stopped
```


Localhost-only binding for use behind a reverse proxy:

```yaml
services:
  zabbix-websocket-bridge:
    image: ghcr.io/voltkraft/zabbix-websocket-bridge:latest
    pull_policy: always
    environment:
      HOST: 0.0.0.0
      PORT: 8080
      LOG_LEVEL: info
    ports:
      - "127.0.0.1:8080:8080"
    restart: unless-stopped
```

Start a Compose deployment:

```sh
docker compose up -d
```

The included `compose.yaml` uses the same GHCR image and publishes port `8080` on the host.

## Example curl requests

Health check:

```sh
curl http://localhost:8080/health
```

Batch JSON-RPC request:

```sh
curl -X POST http://localhost:8080/api/v1/jsonrpc/batch \
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
HOST=0.0.0.0 PORT=8080 LOG_LEVEL=info python -m zabbix_websocket_bridge.main
```

Run tests:

```sh
pytest
```

## Container build automation

The `container` workflow builds the GHCR image automatically on:

- Pushes to `main`.
- Version tags matching `v*`.
- Manual `workflow_dispatch` runs.
- Weekly scheduled rebuilds.

Scheduled and manual rebuilds pull the current base image and bypass the build cache, so base image and Python dependency updates are picked up even when the repository did not change.

The workflow first builds a local candidate image and compares it with the currently published `ghcr.io/voltkraft/zabbix-websocket-bridge:latest` image. If the candidate is identical to the latest published image, nothing is pushed. If it differs, the candidate is tagged and published to GHCR.

Published tags include `latest`, branch names, semantic version tags, and commit SHA tags.

## Security considerations

- The bridge does not authenticate or authorize requests. Deploy it behind trusted network controls, an API gateway, or another authentication layer.
- The bridge does not store credentials, sessions, target definitions, request payloads, responses, or cached data.
- Logs are structured and intentionally avoid request payloads and full target URLs with credentials.
- If credentials are embedded in a WebSocket URL, they are used only for the outbound connection and are removed from operational log messages.
- TLS verification is enabled by default for `wss://` targets. Disable it only for controlled development or test environments.
- The container runs as a non-root user.

## License

This project is licensed under the GNU Affero General Public License v3.0. See [LICENSE](LICENSE) for details.
