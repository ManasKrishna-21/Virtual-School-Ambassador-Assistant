# NOVA — 3D Robot Companion & Interactive Kiosk Frontend

A real-time, browser-rendered 3D robot companion built with **React Three Fiber** and **FastAPI**. NOVA serves as the expressive visual avatar and interactive kiosk frontend for the **AI School Ambassador** offline voice assistant.

Commands sent via REST API trigger smooth physics-based 3D animations, synchronized facial expressions, live on-screen captions, and an interactive audience-selection HUD over low-latency WebSockets.

---

## Table of Contents

- [What is Included](#what-is-included)
- [Architecture & Interaction Flow](#architecture--interaction-flow)
- [Allowed Actions & Animation Catalog](#allowed-actions--animation-catalog)
- [Audio & Speech Architecture](#audio--speech-architecture)
- [Audience Selection Feature](#audience-selection-feature)
- [API Contract & Endpoints](#api-contract--endpoints)
- [Local Development Setup](#local-development-setup)
- [Integration with AI School Ambassador](#integration-with-ai-school-ambassador)
- [Configuration Reference](#configuration-reference)
- [Production Deployment Checklist](#production-deployment-checklist)
- [Upgrading to Custom 3D Models (`.glb`)](#upgrading-to-custom-3d-models-glb)
- [Project Layout](#project-layout)

---

## What is Included

- **React + Vite + React Three Fiber Frontend**:
  - Procedural 3D robot mesh with emissive face/torso accents, cyan aura lighting, dynamic ground ring projections, contact shadows, and orbit controls.
  - Spring-physics animation engine for organic motion, head tilts, arm gestures, and expressive posture shifts.
  - Interactive on-screen control HUD with manual action triggers, real-time command log, connection indicator, and live speech captions.
  - Responsive **Audience Selection Modal** (`Parent`, `Student`, `Teacher`, `Visitor`) with auto-dismiss countdown.
- **FastAPI Backend (`main.py`)**:
  - High-performance REST endpoints for triggering actions, querying robot state, and managing audience context.
  - Real-time WebSocket event broadcaster supporting multi-client synchronization.
  - Optional Bearer token authentication for secure environments.
  - In-memory state and connection manager with automatic stale connection pruning.

---

## Architecture & Interaction Flow

```
┌──────────────────────────────────────┐
│  AI School Ambassador Pipeline / CLI │
└──────────────────┬───────────────────┘
                   │ HTTP POST (Actions / State / Audience)
                   ▼
┌──────────────────────────────────────┐
│        FastAPI Backend (8000)        │
└──────────────────┬───────────────────┘
                   │ WebSocket Push (/ws/robots/{robot_id})
                   ▼
┌──────────────────────────────────────┐
│   React Three Fiber Frontend (5173)  │
│  • 3D Animation & Spring Physics     │
│  • Synchronized Speech Captions      │
│  • Interactive Audience HUD Overlay  │
└──────────────────────────────────────┘
```

---

## Allowed Actions & Animation Catalog

NOVA supports **12 distinct action animations** configured in `backend/main.py` and `frontend/src/App.jsx`:

| Action | Icon | Duration | Animation Description & Kiosk Use Case |
|---|:---:|:---:|---|
| `idle` | ◌ | ∞ | Ambient breathing, gentle body sway, and pulsing cyan face glow. |
| `wave` | 👋 | 2.8s | Right or left arm waving gesture with head tilt; welcoming visitors. |
| `nod` | ↕ | 1.8s | Affirmative head nod; signals query understanding or fallback acknowledgment. |
| `greet` | ↗ | 3.0s | Friendly welcoming salute; triggers the audience selection HUD overlay. |
| `think` | ◉ | 3.5s | Hand to chin, reflective pose, orbiting head ring; active during STT & LLM generation. |
| `celebrate` | ✧ | 2.8s | Joyful victory dance with raised arms and glowing cyan chest lights. |
| `speak` | ▶ | 7.0s | Expressive mouth/torso motion synchronized with audio and live question/answer caption. |
| `bow` | 🙇 | 2.5s | Respectful forward bow for formal greetings or departures. |
| `dance` | ♪ | 4.0s | Playful rhythmic dance routine for student engagement. |
| `point` | 👉 | 2.0s | Directing attention towards the lobby or registration desk. |
| `shrug` | 🤷 | 2.0s | Apologetic shoulder shrug; used for out-of-scope queries, guardrail declines, or errors. |
| `attention` | ⚡ | 2.2s | Alert upright posture with glowing amber/cyan eye indicator. |

---

## Audio & Speech Architecture

> [!NOTE]
> In this integrated kiosk setup, **browser speech synthesis (`speechSynthesis`) is explicitly muted** in `App.jsx` to eliminate robotic or inconsistent client voices.

Audio playback is handled exclusively by the **AI School Ambassador** offline pipeline using the high-fidelity **Kokoro-82M neural TTS** engine (`af_bella` female voice @ 24 kHz) routed through physical kiosk speakers. When the pipeline posts a `speak` action:
1. The 3D robot performs synchronized speaking gestures (jaw/mouth glow pulsing, expressive torso shifts).
2. Live synchronized captions display both the visitor's question and NOVA's answer on the kiosk screen.
3. High-quality neural speech plays simultaneously through the kiosk audio hardware.

---

## Audience Selection Feature

NOVA includes an interactive **Audience Selection** modal designed for touchscreens:

1. When the pipeline triggers a `greet` action upon visitor arrival, the frontend immediately displays an on-screen audience card with four choices:
   - 👨‍👩‍👧 **Parent** (Admissions, fee schedules, transportation, safety)
   - 🎓 **Student** (Clubs, timetable, cafeteria, sports, events)
   - 👩‍🏫 **Teacher** (Staff directory, academic policies, calendar)
   - 🧭 **Visitor** (Campus tours, directions, front office contacts)
2. **Auto-Default Timeout**: If no selection is tapped within **5 seconds**, the HUD automatically posts `visitor` to the backend and smoothly closes.
3. **Pipeline Ingestion**: The voice pipeline queries `GET /api/robots/{robot_id}/audience` to consume the chosen audience, adapting the LLM answer style and prioritizing relevant retrieval chunks.

---

## API Contract & Endpoints

Complete reference is available in [NOVA_API_REFERENCE.md](file:///c:/Users/manas/OneDrive/Desktop/WeGuide/School%20Ambassador/robot-companion-prototype/NOVA_API_REFERENCE.md).

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health status. |
| `GET` | `/api/robots/{robot_id}/state` | Returns connection count, last action, and acting/idle status. |
| `POST` | `/api/robots/{robot_id}/actions` | Validates an action and broadcasts it to connected browsers via WebSocket. |
| `POST` | `/api/robots/{robot_id}/audience` | Sets the audience type (`parent`, `student`, `teacher`, `visitor`) and notifies HUD. |
| `GET` | `/api/robots/{robot_id}/audience` | Reads and consumes the audience selection (consume-once per turn). |
| `WS` | `/ws/robots/{robot_id}` | Real-time WebSocket stream for push-driven animations and events. |

### Example Action Requests

#### Trigger a Gesture
```bash
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H "Content-Type: application/json" \
  -d '{"action": "wave", "params": {"side": "right", "speed": 1.0}}'
```

#### Trigger Speech with Captions
```bash
curl -X POST http://127.0.0.1:8000/api/robots/nova/actions \
  -H "Content-Type: application/json" \
  -d '{
    "action": "speak",
    "text": "Welcome to Oakridge International Academy! How can I assist you today?",
    "params": {"question": "Hello!"}
  }'
```

#### Set Audience Category
```bash
curl -X POST http://127.0.0.1:8000/api/robots/nova/audience \
  -H "Content-Type: application/json" \
  -d '{"audience": "parent"}'
```

---

## Local Development Setup

### 1. Start the FastAPI Backend

```bash
cd backend

# Create and activate virtual environment
python -m venv .venv

# On Windows PowerShell:
.venv\Scripts\Activate.ps1
# On Linux / macOS:
# source .venv/bin/activate

pip install -r requirements.txt

# Configure environment
copy .env.example .env

# Run server on port 8000
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Verify backend health at `http://127.0.0.1:8000/health` or browse Swagger docs at `http://127.0.0.1:8000/docs`.

### 2. Start the React Frontend

In a second terminal:

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

Open the printed Vite URL (usually `http://localhost:5173`). The top bar will display **WS: Connected** with a green status indicator.

---

## Integration with AI School Ambassador

The `school-ambassador` package automatically interfaces with this service when `robot.enabled: true` in its `config.yaml`.

Interaction sequence:
1. `school-ambassador` initializes `RobotController` pointing to `http://127.0.0.1:8000`.
2. Voice detected → `robot.trigger("greet")` (Frontend salutes and displays audience prompt).
3. STT / RAG query processing → `robot.trigger("think")` (Robot engages reflective posture).
4. Audio response playback → `robot.speak(answer, question=query)` (Robot animates speech; captions display on screen).
5. Unrecognized query / Fallback → `robot.trigger("nod")` (Affirmative nod).
6. Inappropriate query / Error → `robot.trigger("shrug")` (Apologetic shrug).

---

## Configuration Reference

### Backend (`backend/.env`)

```env
API_TOKEN=                         # Leave empty for open local dev; set for authenticated deployments
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

### Frontend (`frontend/.env`)

```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_API_TOKEN=                    # Matches backend API_TOKEN if configured
```

---

## Production Deployment Checklist

1. **Enable HTTPS / WSS**: Terminate TLS at a reverse proxy (e.g., NGINX, Caddy, or Cloudflare) to ensure secure WebSocket transport.
2. **Configure API Security**: Set a cryptographically random `API_TOKEN`. REST calls must pass `Authorization: Bearer <token>`, and WebSocket connections require `?token=<token>`.
3. **Stateless Multi-Instance Scaling**: If deploying multiple backend replicas, replace the in-memory `ConnectionManager` with a Redis Pub/Sub backend.
4. **Static Hosting**: Build and serve the frontend via NGINX or static CDN:
   ```bash
   cd frontend
   npm run build
   ```

---

## Upgrading to Custom 3D Models (`.glb`)

The starter robot uses procedural geometry built with Three.js primitives so that the prototype runs immediately with zero external 3D asset downloads.

To substitute a photorealistic or branded mascot:
1. Export your rigged 3D character from Blender / Maya in binary glTF format (`.glb`).
2. Place the file at `frontend/public/models/nova.glb`.
3. In `frontend/src/App.jsx`, replace `RobotModel` using `@react-three/drei`'s `useGLTF`:
   ```jsx
   import { useGLTF, useAnimations } from '@react-three/drei';

   function RiggedRobotModel({ command }) {
     const group = useRef();
     const { scene, animations } = useGLTF('/models/nova.glb');
     const { actions } = useAnimations(animations, group);

     useEffect(() => {
       if (command?.action && actions[command.action]) {
         actions[command.action].reset().fadeIn(0.2).play();
         return () => actions[command.action].fadeOut(0.2);
       }
     }, [command, actions]);

     return <primitive ref={group} object={scene} />;
   }
   ```
4. Map animation clip names in your GLB file to NOVA's standard action catalog (`idle`, `wave`, `nod`, `greet`, `think`, `celebrate`, `speak`, `bow`, `dance`, `point`, `shrug`, `attention`).

---

## Project Layout

```text
robot-companion-prototype/
├── README.md                 # Project documentation and developer guide
├── NOVA_API_REFERENCE.md     # Full HTTP & WebSocket API specification
├── backend/                  # FastAPI service
│   ├── .env.example          # Environment template
│   ├── main.py               # REST API, WebSocket hub, audience & action handlers
│   └── requirements.txt      # Python dependencies (fastapi, uvicorn, pydantic, websockets)
└── frontend/                 # React Three Fiber web application
    ├── .env.example          # Frontend environment template
    ├── index.html            # HTML entry point
    ├── package.json          # Node dependencies (three, @react-three/fiber, @react-three/drei)
    ├── vite.config.js        # Vite bundler configuration
    └── src/
        ├── App.jsx           # 3D Canvas, procedural robot, audience HUD, action controls
        ├── main.jsx          # React DOM bootstrap
        └── styles.css        # Cyberpunk holographic styling & HUD overlay layout
```
