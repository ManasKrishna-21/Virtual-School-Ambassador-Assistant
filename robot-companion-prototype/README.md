# NOVA — Browser-based 3D Robot Companion

A runnable starter prototype for a browser-rendered 3D companion robot with API-triggered actions.

## What is included

- React + Vite + React Three Fiber frontend.
- Procedural 3D robot geometry, emissive face/torso details, lighting, shadows, idle movement, gesture animations, and orbit controls.
- FastAPI backend with REST action endpoints, state endpoint, and WebSocket push events.
- Browser speech using the Web Speech API (`speechSynthesis`) for a simple no-cost voice prototype.
- Simple in-memory state and connection manager for local development.

> Visual note: the included robot is a custom procedural prototype made from 3D shapes. It is not photorealistic yet. For a production-quality look, replace `RobotModel` with a licensed, rigged `.glb`/`.gltf` asset that includes polished PBR materials and animation clips.

## Requirements

- Node.js `20.19+` or `22.12+` (recommended: current LTS)
- Python 3.10+
- A modern browser with WebGL support

## Run locally

### 1. Start the API backend

```bash
cd backend
python -m venv .venv
# macOS/Linux
source .venv/bin/activate
# Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

On Windows, create `.env` by copying `.env.example` manually if `cp` is unavailable.

Open `http://127.0.0.1:8000/docs` to explore the API.

### 2. Start the browser frontend in a second terminal

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Open the URL printed by Vite (usually `http://localhost:5173`). The UI should show the WebSocket as connected. Use the action buttons to test gestures and speech.

### 3. Trigger the robot from another terminal / application

Wave:

```bash
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H 'Content-Type: application/json' \
  -d '{"action":"wave","params":{"side":"right","speed":1.0}}'
```

Speak:

```bash
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H 'Content-Type: application/json' \
  -d '{"action":"speak","text":"Hello! I'm Nova, your companion robot."}'
```

Read state:

```bash
curl http://127.0.0.1:8000/api/robots/nova/state
```

Allowed actions: `idle`, `wave`, `nod`, `greet`, `think`, `celebrate`, and `speak`.

## API contract

- `POST /api/robots/{robot_id}/actions` — validate an action and broadcast it to connected browser clients.
- `GET /api/robots/{robot_id}/state` — return the last known state and client count.
- `WS /ws/robots/{robot_id}` — receive action events and connection status.
- `GET /health` — basic health check.

The REST call still returns an accepted action if no browser is connected, but it cannot animate a closed browser. This starter does not persist commands or state across backend restarts.

## Configuration

`frontend/.env.example`:

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
```

`backend/.env.example` documents the backend environment values. The sample intentionally works locally without a token. Set `API_TOKEN` before exposing the API outside your machine; when set, REST calls require `Authorization: Bearer <token>` and WebSocket connections require `?token=<token>`.

## Production checklist

1. **Use HTTPS/WSS** and set explicit CORS origins.
2. Set a strong `API_TOKEN`; for a public production app, replace the demo query-token WebSocket flow with short-lived, single-use WebSocket tickets or secure cookie authentication.
3. Replace in-memory connections/state with Redis or another pub/sub layer if using multiple backend workers or replicas. This starter's manager only works in one process.
4. Add per-user/robot authorization, rate limits, action queueing, command IDs/idempotency and audit logging.
5. Serve the frontend from a CDN/static host and run FastAPI as a separate service.
6. Use a licensed rigged GLB model, compress large textures/meshes, and profile on target devices.
7. Browser speech voices vary by operating system/browser. Use a TTS provider if you need a consistent branded voice; do not put provider secrets in frontend code.

## Upgrade the visual model

The default robot is procedural so the demo starts without a separate 3D asset. To move toward a genuinely realistic companion, obtain a licensed humanoid/robot model with a clean rig and PBR materials. Export it as `GLB` (glTF binary), then place it at `frontend/public/models/nova.glb`. Use React Three Fiber's Drei `useGLTF('/models/nova.glb')` and `useAnimations(gltf.animations, rootRef)` to replace `RobotModel`; map the action names (`wave`, `nod`, `greet`, `think`, `celebrate`, `idle`) to the model's actual animation clip names. If the asset doesn't contain those clips, create them in Blender or your 3D tool before integration. `GLB` is supported by Three.js's glTF loader; model licensing and animation naming should be checked before deployment.

## Project layout

```text
robot-companion-prototype/
├── README.md
├── backend/
│   ├── .env.example
│   ├── main.py
│   └── requirements.txt
└── frontend/
    ├── .env.example
    ├── index.html
    ├── package.json
    ├── src/
    │   ├── App.jsx
    │   ├── main.jsx
    │   └── styles.css
    └── vite.config.js
```
