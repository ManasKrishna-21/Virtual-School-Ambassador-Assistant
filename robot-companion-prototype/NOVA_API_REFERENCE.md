# NOVA Robot Companion — API Reference

> **Version:** 0.1.0  
> **Base URL:** `http://127.0.0.1:8000` (configurable via `VITE_API_BASE_URL` / `API_TOKEN` env vars)  
> **Protocol:** HTTP/REST + WebSocket  
> **Auth:** Optional Bearer token (`Authorization: Bearer <token>`)

---

## Overview

The NOVA Robot API lets any software client remotely control the browser-rendered 3D robot companion. Commands are sent via HTTP REST endpoints; the result is pushed in real-time to all connected browser viewers over WebSocket.

```
Client (REST)  ──POST──►  FastAPI Backend  ──broadcast──►  Browser WebSocket  ──►  3D Robot Animation
```

---

## Authentication

Authentication is **optional** when `API_TOKEN` env-var is not set (local dev).  
When `API_TOKEN` is set, every request must carry:

```
Authorization: Bearer <your-token>
```

WebSocket connections pass the token as a query parameter:
```
ws://host/ws/robots/{robot_id}?token=<your-token>
```

---

## Endpoints

### `GET /health`

Returns service health. Requires no auth.

**Response `200`:**
```json
{ "status": "ok", "service": "nova-robot-api" }
```

---

### `GET /api/robots/{robot_id}/state`

Returns the current state of a robot unit.

| Parameter  | Type   | Location | Description              |
|------------|--------|----------|--------------------------|
| `robot_id` | string | path     | Robot identifier, e.g. `nova` |

**Response `200`:**
```json
{
  "robot_id": "nova",
  "status": "idle",           // "idle" | "acting"
  "last_action": "greet",
  "last_action_at": "2026-10-26T06:42:11.330Z",
  "connected_clients": 2
}
```

**Possible errors:**
| Code | Reason |
|------|--------|
| 401  | Missing or invalid Bearer token |

---

### `POST /api/robots/{robot_id}/actions`

Sends a command to the robot. The action is broadcast in real-time to all connected WebSocket viewers.

**Path parameter:**

| Parameter  | Type   | Description              |
|------------|--------|--------------------------|
| `robot_id` | string | Robot identifier (`nova`) |

**Request body (JSON):**

```json
{
  "action": "wave",
  "text":   null,
  "params": {
    "side":  "right",
    "speed": 1.0
  }
}
```

| Field    | Type            | Required | Description |
|----------|-----------------|----------|-------------|
| `action` | ActionName      | ✅        | The animation to trigger (see table below) |
| `text`   | string (≤500ch) | Only for `speak` | Text for voice synthesis |
| `params` | object          | ❌        | Optional animation modifiers |

**`params` keys:**

| Key     | Type   | Range       | Default | Description |
|---------|--------|-------------|---------|-------------|
| `speed` | float  | 0.25 – 2.0  | `1.0`   | Playback speed multiplier |
| `side`  | string | `left` \| `right` \| `both` | `right` | Which arm to use (applies to `wave`, `point`) |

**Response `202`:**
```json
{
  "accepted": true,
  "request_id": "c47a2f89-...",
  "robot_id": "nova",
  "action": "wave",
  "delivered_to_clients": 1,
  "message": "Action broadcast to connected browser clients."
}
```

**Possible errors:**
| Code | Reason |
|------|--------|
| 401  | Invalid token |
| 422  | Validation error (see detail field) |

---

## Actions Reference

| Action      | Duration | Description | Notable Effects |
|-------------|----------|-------------|-----------------|
| `idle`      | ∞        | Default breathing pose | Gentle body sway, eye blink |
| `wave`      | 2.8 s    | Friendly arm wave | `params.side` controls which arm; wrist oscillation |
| `nod`       | 1.8 s    | Head affirmation nod | Triple head dip |
| `greet`     | 3.0 s    | Combined wave + nod | Both arms rise, double nod |
| `think`     | 3.5 s    | Reflective head tilt | Head turns right, one-eye blink, antenna glow |
| `celebrate` | 2.8 s    | Joy reaction | Both arms raise, body bounce, chest strobe, particles |
| `speak`     | 7.0 s    | Voice synthesis | Requires `text` field; mouth animates; browser TTS plays |
| `bow`       | 2.5 s    | Respectful bow | Torso + head lean forward |
| `dance`     | 4.0 s    | Rhythmic motion | Full body sway, arm swing |
| `point`     | 2.0 s    | Directional point | Single arm extends forward; `params.side` selects arm |
| `shrug`     | 2.0 s    | Unsure gesture | Both arms raise then drop, slight torso wobble |
| `attention` | 2.2 s    | Alert stance | Upright posture, bright eyes, antenna pulse |

---

## WebSocket

**URL:** `ws://{host}/ws/robots/{robot_id}[?token=<token>]`

The WebSocket is **server-push only** for actions. Clients send only keepalive pings.

### Messages sent **by the server**

#### `connection` — sent immediately on connect
```json
{
  "event": "connection",
  "status": "connected",
  "robot_id": "nova",
  "connected_clients": 1,
  "server_time": "2026-10-26T06:42:00.000Z"
}
```

#### `action` — sent whenever a REST action is triggered
```json
{
  "event":      "action",
  "request_id": "c47a2f89-...",
  "robot_id":   "nova",
  "action":     "greet",
  "text":        null,
  "params":     { "speed": 1.0 },
  "created_at": "2026-10-26T06:42:11.330Z",
  "source":     "rest_api"
}
```

#### `pong` — reply to client ping
```json
{ "event": "pong", "server_time": "2026-10-26T06:42:05.100Z" }
```

### Messages sent **by the client**

#### `ping` — keepalive
```json
{ "event": "ping" }
```

---

## Code Examples

### cURL

```bash
# Trigger a greet
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H "Content-Type: application/json" \
  -d '{"action":"greet"}'

# Make Nova speak
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H "Content-Type: application/json" \
  -d '{"action":"speak","text":"Hello, I am Nova!"}'

# Wave left arm at half speed
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H "Content-Type: application/json" \
  -d '{"action":"wave","params":{"side":"left","speed":0.5}}'
```

### JavaScript (fetch)

```js
const API = 'http://127.0.0.1:8000';

async function sendAction(action, extras = {}) {
  const res = await fetch(`${API}/api/robots/nova/actions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ action, ...extras }),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

// Examples
await sendAction('wave', { params: { side: 'right', speed: 1.2 } });
await sendAction('speak', { text: 'Hello from JavaScript!' });
await sendAction('dance');
await sendAction('celebrate');
```

### Python (httpx)

```python
import httpx

client = httpx.Client(base_url="http://127.0.0.1:8000")

def send_action(action: str, text: str | None = None, params: dict | None = None):
    payload = {"action": action}
    if text:   payload["text"]   = text
    if params: payload["params"] = params
    r = client.post("/api/robots/nova/actions", json=payload)
    r.raise_for_status()
    return r.json()

send_action("greet")
send_action("speak", text="Hello world!")
send_action("wave",  params={"side": "both", "speed": 1.5})
```

### WebSocket (JavaScript browser)

```js
const ws = new WebSocket('ws://127.0.0.1:8000/ws/robots/nova');

ws.onopen = () => ws.send(JSON.stringify({ event: 'ping' }));

ws.onmessage = ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.event === 'action') {
    console.log('Robot should:', msg.action, msg.params);
    // Your animation logic here
  }
};
```

---

## Environment Variables

### Backend (`.env` in `/backend`)

| Variable       | Default                                          | Description |
|----------------|--------------------------------------------------|-------------|
| `API_TOKEN`    | `""` (auth disabled)                            | Shared secret for Bearer auth |
| `CORS_ORIGINS` | `http://localhost:5173,http://127.0.0.1:5173`  | Comma-separated allowed origins |

### Frontend (`.env` in `/frontend`)

| Variable            | Default                  | Description |
|---------------------|--------------------------|-------------|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Backend URL |
| `VITE_API_TOKEN`    | `""` (no auth)           | Bearer token sent to backend |

---

## Running Locally

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Interactive API docs available at: `http://127.0.0.1:8000/docs`

### Frontend
```bash
cd frontend
npm install
npm run dev         # → http://localhost:5173
```

---

## Architecture

```
robot-companion-prototype/
├── backend/
│   ├── main.py            ← FastAPI app (REST + WebSocket)
│   ├── requirements.txt
│   └── .env               ← API_TOKEN, CORS_ORIGINS
└── frontend/
    ├── src/
    │   ├── App.jsx         ← React + Three.js robot with 12 actions
    │   └── styles.css      ← Fullscreen cinematic HUD UI
    ├── index.html
    └── .env                ← VITE_API_BASE_URL, VITE_API_TOKEN
```

### Key design decisions

1. **Stateless action relay** — The backend stores only the last action in memory. It broadcasts to all live WebSocket clients and returns the `delivered_to_clients` count.
2. **Spring physics animations** — The frontend uses a critically-damped spring integrator (`springStep`) instead of exponential damping for natural, physically-based motion.
3. **ACESFilmic tone mapping** — The Three.js renderer uses ACES Filmic tone mapping for a cinematic, high-fidelity visual result.
4. **Auto-idle** — Every action has a defined duration. The robot automatically returns to idle after it completes, with no extra API call required.
5. **WebSocket keepalive** — Clients send `{ event: "ping" }` messages to keep the connection alive across proxies and NAT firewalls.

---

*NOVA Robot Companion — © 2026*
