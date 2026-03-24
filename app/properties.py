"""Environment-driven configuration constants."""

import os

# LLM Specific
CIRCUIT_LLM_API_APP_KEY = os.environ.get('CIRCUIT_LLM_API_APP_KEY', "cdc-uber-agent")
CIRCUIT_LLM_API_CLIENT_ID = os.environ.get('CIRCUIT_LLM_API_CLIENT_ID', "cdc-uber-agent")
#CIRCUIT_LLM_API_CLIENT_SECRET = os.environ.get('CIRCUIT_LLM_API_CLIENT_SECRET', "TM-s5QvU-4a5G-KhOLNN14Jd7sHcv8zPLW69LisZ4-ZKaDXjeMtyV7bLnJ2FBU7c")
CIRCUIT_LLM_API_MODEL_NAME = os.environ.get('CIRCUIT_LLM_API_MODEL_NAME', "gpt-4.1-mini")
CIRCUIT_LLM_API_ENDPOINT = os.environ.get('CIRCUIT_LLM_API_ENDPOINT', "http://aiml-cisco-brain-api-svc.default.svc.cluster.local:9000")
CIRCUIT_LLM_API_VERSION = os.environ.get('CIRCUIT_LLM_API_VERSION', "2025-04-01-preview")

JWKS_URI = os.environ.get('JWKS_URI', "https://int-id.cisco.com/oauth2/ausptxawhvMktR9zU1d7/v1/keys")
AUDIENCE = os.environ.get('AUDIENCE', "https://service.agent.circuit.agent.ragaas.support")
ISSUER = os.environ.get('ISSUER', "https://int-id.cisco.com/oauth2/ausptxawhvMktR9zU1d7")
CIRCUIT_CLIENT_ID = os.environ.get('CIRCUIT_CLIENT_ID', "0oaoy45kspjt6GvjB1d7")

OAUTH_ENDPOINT = os.environ.get('OAUTH_ENDPOINT', "https://int-id.cisco.com/oauth2/default/v1/token")

# Full URL to the chat-history endpoint (no path appended by code).
# Example: http://host:7080/api/v2.0/chat_history
CHAT_HISTORY_URL = os.environ.get('CHAT_HISTORY_URL', 'http://localhost:7050/api/v1.0/chat_history')

# Agent registry service (sole source of sub-agent cards; set via environment)
AGENT_REGISTRY_URL = os.environ.get('AGENT_REGISTRY_URL', 'http://0.0.0.0:8080')
AGENT_REGISTRY_APP_ID = os.environ.get('AGENT_REGISTRY_APP_ID', 'circuit-external-agent')
AGENT_REGISTRY_REQUEST_TYPE = os.environ.get('AGENT_REGISTRY_REQUEST_TYPE', 'api')
# Comma-separated categories to request from registry (e.g. CDC,marketing)
_AGENT_REGISTRY_CATEGORIES_ENV = os.environ.get('AGENT_REGISTRY_CATEGORIES', 'CDC Uber Agent, CDC Uber Assistant')
AGENT_REGISTRY_CATEGORIES = [c.strip() for c in _AGENT_REGISTRY_CATEGORIES_ENV.split(',') if c.strip()]
# Initial load retries when registry is temporarily unavailable (e.g. K8s startup order).
# Delay between retries: first delay in seconds; backoff multiplier for subsequent retries.
AGENT_REGISTRY_INITIAL_RETRIES = int(os.environ.get('AGENT_REGISTRY_INITIAL_RETRIES', '5'))
AGENT_REGISTRY_INITIAL_RETRY_DELAY_SECONDS = float(os.environ.get('AGENT_REGISTRY_INITIAL_RETRY_DELAY_SECONDS', '3'))
AGENT_REGISTRY_INITIAL_RETRY_BACKOFF = float(os.environ.get('AGENT_REGISTRY_INITIAL_RETRY_BACKOFF', '2.0'))

# Optional push notification auth for sub-agents (id, secret/token) when sending to the relay.
# Sub-agent receives these in PushNotificationConfig so it can authenticate when sending push.
PUSH_NOTIFICATION_AUTH_ID = os.environ.get('PUSH_NOTIFICATION_AUTH_ID', '').strip() or None
PUSH_NOTIFICATION_AUTH_SECRET = os.environ.get('PUSH_NOTIFICATION_AUTH_SECRET', '').strip() or None
PUSH_NOTIFICATION_AUTH_URL = os.environ.get('PUSH_NOTIFICATION_AUTH_URL', '').strip() or None  # alternative to secret


def get_push_notification_auth() -> dict:
    """
    Return optional push notification auth for sub-agents: id, token/credentials.
    Used to build PushNotificationConfig so sub-agent can authenticate when sending push.
    Keys: id (optional), token (optional), credentials (optional, for authentication.schemes).
    """
    out = {}
    if PUSH_NOTIFICATION_AUTH_ID:
        out['id'] = PUSH_NOTIFICATION_AUTH_ID
    if PUSH_NOTIFICATION_AUTH_SECRET:
        out['credentials'] = PUSH_NOTIFICATION_AUTH_SECRET
    if PUSH_NOTIFICATION_AUTH_URL:
        out['url'] = PUSH_NOTIFICATION_AUTH_URL
    return out


# Async push delivery: URL of the WebSocket server that receives async sub-agent
# responses and pushes them to the UI.  The WebSocket server is the only caller of
# the orchestration API (UI -> WebSocket server -> orchestration agent).  When the
# relay sends to /api/webhooks/async-response we forward the payload to this URL.
# Must include the full path, e.g.:
#   http://cdcai-microsvc-uber-assistant-frontend-svc.ns-qry-aiml-stg-api.svc.cluster.local:8006/ciscoua/api/v1/ws/async/response
FRONTEND_ASYNC_PUSH_URL = os.environ.get("FRONTEND_ASYNC_PUSH_URL", "").strip() or None

# Agent card refresh: interval in seconds to re-fetch sub-agent cards in the background.
# Set to 0 to disable periodic refresh (cards still loaded lazily on first use).
# Suggested: 300 (5 min) to 900 (15 min); agent cards change infrequently.
AGENT_CARD_REFRESH_INTERVAL_SECONDS = int(
    os.environ.get('AGENT_CARD_REFRESH_INTERVAL_SECONDS', '300')
)

# Live agent mode: phrase(s) that trigger async/live agent mode. Once the user
# says one of these, we send the relay URL to the sub-agent for push; caller
# should send live_agent_mode=true on subsequent messages. Comma-separated in env.
_LIVE_AGENT_TRIGGER_ENV = os.environ.get('LIVE_AGENT_TRIGGER_PHRASES', '')
LIVE_AGENT_TRIGGER_PHRASES = [
    p.strip().lower() for p in _LIVE_AGENT_TRIGGER_ENV.split(',') if p.strip()
] if _LIVE_AGENT_TRIGGER_ENV else [
    'i want to talk to a human',
]

# When live agent mode is active, force-route to the agent whose slug contains
# this substring (case-insensitive).  Prevents the LLM from accidentally
# routing live-agent conversations to an agent that doesn't support async push.
LIVE_AGENT_TARGET_AGENT = os.environ.get('LIVE_AGENT_TARGET_AGENT', 'licensing').strip().lower()

# Predefined responses: fixed Q&A. If the user's query matches (case-insensitive
# substring), we return the answer without calling a sub-agent. Answer is sent in A2A format.
# List of (list of trigger phrases, answer text). If any phrase is in the query, use that answer.
PREDEFINED_RESPONSES = [
    (['what hours are you open', 'when are you open', 'opening hours', 'business hours'], 'We are open from 9-5.'),
]

# Redis (shared state for multi-pod deployment and crash recovery).
# When REDIS_HOST is set, conversation records, task indexes, and pending
# webhooks are persisted to Redis enabling cross-pod webhook routing. Falls
# back to in-memory-only when REDIS_HOST is empty or Redis is unreachable.
REDIS_HOST = os.environ.get('REDIS_HOST', '10.68.81.4').strip() or None
REDIS_PORT = int(os.environ.get('REDIS_PORT', '6379'))
REDIS_DB = int(os.environ.get('REDIS_DB', '0'))
REDIS_TTL_TASK_MAPPING = int(os.environ.get('REDIS_TTL_TASK_MAPPING', '28800'))       # 8h (conv + task keys)
REDIS_TTL_PENDING_WEBHOOK = int(os.environ.get('REDIS_TTL_PENDING_WEBHOOK', '3600'))   # 1 hour

# Number of recent conversation turns to include directly in prompts.
# History API handles summarization of older turns separately.
RECENT_TURNS = int(os.environ.get('RECENT_TURNS', '15'))