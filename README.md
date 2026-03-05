# Mock WebSocket Server

A mock WebSocket server for the CIRCUIT User Assistant Service, designed for testing and development purposes. Built with FastAPI, Pydantic, and structured logging.

## Features

- **WebSocket Support**: Full WebSocket implementation with subprotocol negotiation (`circuit.v1`, `circuit.v2`)
- **Canned Responses**: Configurable mock responses based on message type
- **Latency Simulation**: Realistic latency simulation with configurable delays and random spikes
- **Pydantic Models**: Full request/response validation with Pydantic v2
- **Structured Logging**: Production-ready logging with StructLog (GCP Cloud Logging compatible)
- **Kubernetes Ready**: Includes deployment manifests, health checks, and HPA configuration

## Quick Start

### Local Development

1. **Create virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server**:
   ```bash
   python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

4. **Test the connection**:
   ```bash
   # Using websocat (install: brew install websocat)
   websocat ws://localhost:8000/ciscoua/api/v1/ws
   
   # Or using wscat (install: npm install -g wscat)
   wscat -c ws://localhost:8000/ciscoua/api/v1/ws
   ```

### Docker

```bash
# Build
docker build -t mock-websocket-server .

# Run
docker run -p 8000:8000 mock-websocket-server
```

### Deploy to GKE

1. **Build and push image**:
   ```bash
   # Set your project ID
   export PROJECT_ID=your-gcp-project-id
   
   # Build and push
   docker build -t gcr.io/$PROJECT_ID/mock-websocket-server:latest .
   docker push gcr.io/$PROJECT_ID/mock-websocket-server:latest
   ```

2. **Update deployment**:
   ```bash
   # Replace PROJECT_ID in deployment.yaml
   sed -i "s/PROJECT_ID/$PROJECT_ID/g" k8s/deployment.yaml
   ```

3. **Deploy**:
   ```bash
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/deployment.yaml
   kubectl apply -f k8s/service.yaml
   ```

4. **Get external IP**:
   ```bash
   kubectl get service mock-websocket-server
   ```

## API Endpoints

### HTTP Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /health/live` | Liveness probe |
| `GET /health/ready` | Readiness probe |
| `GET /stats` | Service statistics |
| `GET /docs` | Swagger UI (dev only) |

### WebSocket Endpoints

| Endpoint | Description |
|----------|-------------|
| `WS /ws` | Main WebSocket endpoint |
| `WS /ws/{client_id}` | WebSocket with client ID |

## Message Format

### Incoming Messages

```json
{
  "type": "user_query",
  "payload": {
    "query": "What is my account balance?",
    "language": "en"
  },
  "metadata": {
    "session_id": "session-123",
    "correlation_id": "corr-456"
  }
}
```

### Supported Message Types

| Type | Description |
|------|-------------|
| `user_query` | User question to the assistant |
| `ping` | Connection health check |
| `get_history` | Retrieve conversation history |
| `orchestrate` | Trigger orchestration action |
| `subscribe` | Subscribe to topics |
| `unsubscribe` | Unsubscribe from topics |

### Response Format

```json
{
  "type": "assistant_response",
  "payload": {
    "message": "Your account balance is...",
    "confidence": 0.92,
    "sources": ["knowledge_base"],
    "suggested_actions": ["Ask follow-up"]
  },
  "metadata": {
    "correlation_id": "corr-456",
    "timestamp": "2024-01-15T10:30:00Z",
    "latency_ms": 150
  }
}
```

## A2A Plain Text Queries

The server also supports **plain text queries** that return **A2A (Agent-to-Agent) JSON-RPC 2.0** responses. This is useful for simple text-based interactions without structured JSON input.

### How It Works

1. Send a plain text message (not JSON) via WebSocket
2. The server matches the text against configured patterns using **contains-based matching**
3. Returns an A2A JSON-RPC 2.0 formatted response

### Supported Queries

| Query Type | Match Patterns | Description |
|------------|----------------|-------------|
| **Welcome** | `welcome` | Welcome message |
| **Licencing Configuration** | `licencing configuration`, `license configuration`, `config` | License configuration details |
| **Licencing Information** | `licencing information`, `license information`, `licence info` | License status and details |
| **Product Information** | `product information`, `product info`, `product` | Product/device information |

> **Note**: Matching is case-insensitive and uses contains logic. For example, "show me product info" matches "product info".

### Sample Queries

```bash
# Welcome
wscat -c ws://localhost:8000/ws -x 'welcome'
wscat -c ws://localhost:8000/ws -x 'welcome to cisco'

# Licencing Configuration
wscat -c ws://localhost:8000/ws -x 'licencing configuration'
wscat -c ws://localhost:8000/ws -x 'show me the config'

# Licencing Information
wscat -c ws://localhost:8000/ws -x 'licencing information'
wscat -c ws://localhost:8000/ws -x 'license info'

# Product Information
wscat -c ws://localhost:8000/ws -x 'product information'
wscat -c ws://localhost:8000/ws -x 'show product'

# Default (no match)
wscat -c ws://localhost:8000/ws -x 'hello there'
```

### A2A Response Format

```json
{
  "jsonrpc": "2.0",
  "id": "req_a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "result": {
    "kind": "task",
    "id": "task_5f8d2a1b-c3e4-4f6a-8b9c-0d1e2f3a4b5c",
    "contextId": "9a8b7c6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d",
    "status": {
      "state": "completed",
      "message": null,
      "timestamp": "2026-02-09T15:30:00.000000Z"
    },
    "artifacts": [
      {
        "artifactId": "art_1234abcd-5678-efgh-9012-ijkl3456mnop",
        "name": "Response from orchestration",
        "parts": [
          {
            "kind": "text",
            "text": "Welcome to CIRCUIT Assistant. How can I help you today?"
          }
        ]
      }
    ]
  }
}
```

### Matching Priority

Patterns are matched in the following priority order (first match wins):

1. `licencing configuration` / `license configuration` / `config`
2. `licencing information` / `license information` / `licence info`
3. `product information` / `product info` / `product`
4. `welcome`
5. Default response (if no match)

## Configuration

Configuration via environment variables (prefix: `MOCK_WS_`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_WS_HOST` | `0.0.0.0` | Server bind host |
| `MOCK_WS_PORT` | `8000` | Server bind port |
| `MOCK_WS_ENVIRONMENT` | `development` | Environment (development/production) |
| `MOCK_WS_LOG_LEVEL` | `INFO` | Log level |
| `MOCK_WS_MAX_CONNECTIONS` | `1000` | Max concurrent connections |
| `MOCK_WS_LATENCY_ENABLED` | `true` | Enable latency simulation |
| `MOCK_WS_LATENCY_MIN_MS` | `50` | Min latency (ms) |
| `MOCK_WS_LATENCY_MAX_MS` | `300` | Max latency (ms) |
| `MOCK_WS_LATENCY_SPIKE_PROBABILITY` | `0.05` | Spike probability |
| `MOCK_WS_CANNED_RESPONSES_PATH` | `app/responses/canned_responses.json` | Path to JSON responses file |
| `MOCK_WS_A2A_RESPONSES_PATH` | `app/responses/a2a_responses.json` | Path to A2A responses file |

## Testing

```bash
# Install test dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html
```

## Project Structure

```
mock-websocket-server/
├── app/
│   ├── api/              # API endpoints (health, websocket)
│   ├── core/             # Core logic (connection manager, router, latency)
│   ├── dependencies/     # FastAPI DI providers
│   ├── logging/          # StructLog configuration
│   ├── models/           # Pydantic models (including A2A response models)
│   ├── responses/        # Canned responses JSON
│   │   ├── canned_responses.json   # JSON message responses
│   │   └── a2a_responses.json      # A2A plain text query responses
│   └── services/         # Business logic services
│       ├── message_handler.py      # Routes JSON/plain text messages
│       ├── response_loader.py      # Loads canned responses
│       └── a2a_handler.py          # Handles A2A plain text queries
├── k8s/                  # Kubernetes manifests
├── tests/                # Test suite
├── Dockerfile
├── requirements.txt
└── README.md
```

## License

Internal use only.
