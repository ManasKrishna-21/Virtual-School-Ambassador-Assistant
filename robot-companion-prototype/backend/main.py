from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

load_dotenv()

API_TOKEN = os.getenv("API_TOKEN", "").strip()
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    if origin.strip()
]

app = FastAPI(
    title="NOVA Robot API",
    description="API-controlled actions for the NOVA browser-based 3D companion robot.",
    version="0.1.0",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

ActionName = Literal[
    "idle", "wave", "nod", "greet", "think", "celebrate", "speak",
    "bow", "dance", "point", "shrug", "attention",
]


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: ActionName
    text: str | None = Field(default=None, max_length=500)
    params: dict[str, Any] = Field(default_factory=dict)


class ActionEvent(BaseModel):
    event: Literal["action"] = "action"
    request_id: str
    robot_id: str
    action: ActionName
    text: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    source: Literal["rest_api"] = "rest_api"


class RobotState(BaseModel):
    robot_id: str
    status: Literal["idle", "acting"]
    last_action: ActionName
    last_action_at: str | None
    connected_clients: int


class ConnectionManager:
    """Small single-process connection manager for the starter prototype."""

    def __init__(self) -> None:
        self.active: dict[str, set[WebSocket]] = {}
        self.last_action: dict[str, ActionEvent] = {}

    async def connect(self, robot_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active.setdefault(robot_id, set()).add(websocket)
        await websocket.send_json(
            {
                "event": "connection",
                "status": "connected",
                "robot_id": robot_id,
                "connected_clients": len(self.active.get(robot_id, set())),
                "server_time": utc_now(),
            }
        )

    def disconnect(self, robot_id: str, websocket: WebSocket) -> None:
        connections = self.active.get(robot_id)
        if connections is not None:
            connections.discard(websocket)
            if not connections:
                self.active.pop(robot_id, None)

    async def broadcast(self, robot_id: str, payload: dict[str, Any]) -> int:
        connections = list(self.active.get(robot_id, set()))
        stale: list[WebSocket] = []
        delivered = 0
        for connection in connections:
            try:
                await connection.send_json(payload)
                delivered += 1
            except Exception:
                stale.append(connection)
        for connection in stale:
            self.disconnect(robot_id, connection)
        return delivered


manager = ConnectionManager()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def verify_api_token(authorization: str | None = Header(default=None)) -> None:
    """Optional bearer token: convenient for local development, mandatory when configured."""
    if not API_TOKEN:
        return
    expected = f"Bearer {API_TOKEN}"
    if authorization is None or authorization != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def state_for(robot_id: str) -> RobotState:
    last = manager.last_action.get(robot_id)
    last_action: ActionName = last.action if last else "idle"
    is_acting = False
    if last and last_action != "idle" and manager.active.get(robot_id):
        try:
            action_time = datetime.fromisoformat(last.created_at)
            if action_time.tzinfo is None:
                action_time = action_time.replace(tzinfo=timezone.utc)
            max_durations = {
                "speak": 8.0, "dance": 4.5, "think": 4.0, "greet": 3.5,
                "celebrate": 3.0, "wave": 3.0, "bow": 3.0, "point": 2.5,
                "shrug": 2.5, "attention": 2.5, "nod": 2.0, "idle": 0,
            }
            max_duration = max_durations.get(last_action, 3.0)
            is_acting = (datetime.now(timezone.utc) - action_time).total_seconds() < max_duration
        except ValueError:
            is_acting = False
    return RobotState(
        robot_id=robot_id,
        status="acting" if is_acting else "idle",
        last_action=last_action,
        last_action_at=last.created_at if last else None,
        connected_clients=len(manager.active.get(robot_id, set())),
    )


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "nova-robot-api"}


# ─── Audience Selection (AI School Ambassador integration) ──────
# In-memory audience selection: set by the frontend HUD, read once
# by the pipeline, then auto-reset to None.
_audience_selection: dict[str, str | None] = {}


@app.post(
    "/api/robots/{robot_id}/audience",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(verify_api_token)],
)
async def set_audience(robot_id: str, body: dict[str, str]) -> dict[str, str]:
    """Set the audience type for the current question turn."""
    audience = body.get("audience", "visitor").strip().lower()
    valid = {"parent", "student", "teacher", "visitor"}
    if audience not in valid:
        raise HTTPException(status_code=422, detail=f"audience must be one of {valid}")
    _audience_selection[robot_id] = audience
    # Broadcast to connected clients so the HUD can show confirmation
    await manager.broadcast(robot_id, {
        "event": "audience_set",
        "robot_id": robot_id,
        "audience": audience,
    })
    return {"robot_id": robot_id, "audience": audience}


@app.get(
    "/api/robots/{robot_id}/audience",
    dependencies=[Depends(verify_api_token)],
)
async def get_audience(robot_id: str) -> dict[str, str | None]:
    """Read the current audience selection and reset it (consume-once)."""
    audience = _audience_selection.pop(robot_id, None)
    return {"robot_id": robot_id, "audience": audience}


@app.get("/api/robots/{robot_id}/state", response_model=RobotState, dependencies=[Depends(verify_api_token)])
async def get_robot_state(robot_id: str) -> RobotState:
    return state_for(robot_id)


@app.post(
    "/api/robots/{robot_id}/actions",
    response_model=dict[str, Any],
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(verify_api_token)],
)
async def trigger_action(robot_id: str, request: ActionRequest) -> dict[str, Any]:
    if request.action == "speak" and not request.text:
        raise HTTPException(status_code=422, detail="The 'speak' action requires non-empty text.")
    if request.action != "speak" and request.text is not None:
        # A text payload is harmless, but rejecting it keeps the contract explicit.
        raise HTTPException(status_code=422, detail="Only the 'speak' action accepts the 'text' field.")

    # Keep this starter's action contract constrained to safe, known controls.
    allowed_params = {"side", "speed", "question"}
    unknown_params = set(request.params) - allowed_params
    if unknown_params:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported params: {', '.join(sorted(unknown_params))}",
        )
    if "side" in request.params and request.params["side"] not in {"left", "right", "both"}:
        raise HTTPException(status_code=422, detail="params.side must be left, right, or both")
    if "speed" in request.params:
        try:
            speed = float(request.params["speed"])
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="params.speed must be a number")
        if not 0.25 <= speed <= 2.0:
            raise HTTPException(status_code=422, detail="params.speed must be between 0.25 and 2.0")
        request.params["speed"] = speed

    event = ActionEvent(
        request_id=str(uuid4()),
        robot_id=robot_id,
        action=request.action,
        text=request.text,
        params=request.params,
        created_at=utc_now(),
    )
    manager.last_action[robot_id] = event
    delivered = await manager.broadcast(robot_id, event.model_dump())
    return {
        "accepted": True,
        "request_id": event.request_id,
        "robot_id": robot_id,
        "action": event.action,
        "delivered_to_clients": delivered,
        "message": "Action broadcast to connected browser clients." if delivered else "Action accepted, but no browser is connected right now.",
    }


@app.websocket("/ws/robots/{robot_id}")
async def robot_websocket(websocket: WebSocket, robot_id: str, token: str | None = None) -> None:
    # Browser WebSocket APIs cannot set arbitrary headers. This demo accepts a query token.
    # In public production deployments, use a short-lived single-use ticket or secure cookies.
    if API_TOKEN and token != API_TOKEN:
        await websocket.close(code=1008, reason="Unauthorized")
        return

    await manager.connect(robot_id, websocket)
    try:
        while True:
            # Clients may send keepalive/presence messages; action execution is server-pushed.
            message = await websocket.receive_json()
            if isinstance(message, dict) and message.get("event") == "ping":
                await websocket.send_json({"event": "pong", "server_time": utc_now()})
    except WebSocketDisconnect:
        manager.disconnect(robot_id, websocket)
    except Exception:
        manager.disconnect(robot_id, websocket)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
