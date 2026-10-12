"""FastAPI server of the editor: a thin HTTP layer over ``animai.core.project.Project``.

Routes follow docs/ux-spec.md section 13; decisions and additions are recorded in
docs/schemas.md ("Serveur de l'éditeur"). No pixel or rig logic lives here.
"""
from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from animai.core.errors import AnimaiError
from animai.core.project import Conflict, Project, ProjectError

DEFAULT_APP_DIR = Path(__file__).resolve().parent.parent.parent / "app"
WATCH_INTERVAL_S = 0.3
PING_INTERVAL_S = 15.0
ECHO_DELAY_S = 0.15
NO_STORE = {"Cache-Control": "no-store"}


class Broadcaster:
    """Fan-out of project events to every connected SSE client."""

    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.clients: set[asyncio.Queue] = set()

    def _send(self, event: dict) -> None:
        for queue in list(self.clients):
            queue.put_nowait(event)

    def publish(self, *events: dict) -> None:
        """Thread-safe (endpoints run in a worker thread).

        The event of a write made through the API is sent shortly *after* the
        HTTP response, so the writer knows its new revision before the echo
        arrives and does not mistake it for an external change.
        """
        if self.loop is None:
            return
        for event in events:
            self.loop.call_soon_threadsafe(self.loop.call_later, ECHO_DELAY_S, self._send, event)


def sse_format(event: dict) -> str:
    data = {k: v for k, v in event.items() if k != "type"}
    return f"event: {event['type']}\ndata: {json.dumps(data)}\n\n"


def create_app(project_dir: str | Path, app_dir: str | Path | None = None) -> FastAPI:
    project = Project(project_dir)
    hub = Broadcaster()
    static_dir = Path(app_dir) if app_dir else DEFAULT_APP_DIR

    async def watch() -> None:
        while True:
            await asyncio.sleep(WATCH_INTERVAL_S)
            try:
                events = await asyncio.to_thread(project.poll_changes)
            except Exception:       # a transient file-system error must not stop the watcher
                continue
            for event in events:
                hub._send(event)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        hub.loop = asyncio.get_running_loop()
        task = asyncio.create_task(watch())
        try:
            yield
        finally:
            task.cancel()
            for queue in list(hub.clients):
                queue.put_nowait(None)

    app = FastAPI(title="animAI editor", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.project = project
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        return response

    # ------------------------------------------------------------ errors

    def fail(status: int, message: str, details=None) -> JSONResponse:
        return JSONResponse({"error": message, "details": details}, status_code=status, headers=NO_STORE)

    @app.exception_handler(Conflict)
    async def on_conflict(_: Request, exc: Conflict):
        return JSONResponse(exc.info, status_code=409, headers=NO_STORE)

    @app.exception_handler(ProjectError)
    async def on_project_error(_: Request, exc: ProjectError):
        return fail(exc.status, str(exc), exc.details)

    @app.exception_handler(AnimaiError)
    async def on_core_error(_: Request, exc: AnimaiError):
        return fail(422, f"Opération refusée : {exc}", {"code": "core_error", "core_message": str(exc)})

    @app.exception_handler(RequestValidationError)
    async def on_bad_request(_: Request, exc: RequestValidationError):
        return fail(422, "Requête invalide : paramètre manquant ou mal formé.",
                    [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()])

    @app.exception_handler(StarletteHTTPException)
    async def on_http_error(_: Request, exc: StarletteHTTPException):
        return fail(exc.status_code, "Ressource introuvable." if exc.status_code == 404 else str(exc.detail))

    @app.exception_handler(Exception)
    async def on_crash(_: Request, exc: Exception):
        return fail(500, f"Erreur interne du serveur : {type(exc).__name__}: {exc}")

    def png(data: bytes) -> Response:
        return Response(data, media_type="image/png", headers=NO_STORE)

    def field(payload: dict, name: str, required: bool = True):
        if not isinstance(payload, dict) or (required and name not in payload):
            raise ProjectError(f"Requête invalide : champ « {name} » manquant.", 422)
        return payload.get(name)

    def hidden(hide: str) -> list[str]:
        return [p for p in hide.split(",") if p]

    # ------------------------------------------------------------ project, sprite

    @app.get("/api/project")
    def get_project():
        return project.info()

    @app.post("/api/project/import")
    def import_project(file: UploadFile = File(...), view: str = Form("side")):
        hub.publish(*project.import_image(file.file.read(), view))
        return project.info()

    @app.get("/api/sprite.png")
    def get_sprite(rev: str = ""):
        return png(project.sprite_png())

    @app.get("/api/sprite/segments")
    def get_segments(crop: str = ""):
        box = None
        if crop:
            try:
                box = tuple(int(v) for v in crop.split(","))
                assert len(box) == 4
            except (ValueError, AssertionError):
                raise ProjectError("Paramètre « crop » invalide : attendu x,y,w,h.", 422) from None
        return project.segments(box)

    @app.get("/api/rig/diagnostics")
    def get_diagnostics():
        return project.diagnostics()

    # ------------------------------------------------------------ rig, label map

    @app.get("/api/rig")
    def get_rig():
        return project.read_doc("rig")

    @app.put("/api/rig")
    def put_rig(payload: dict = Body(...)):
        result, event = project.put_rig(field(payload, "base_rev"), field(payload, "data"))
        hub.publish(event)
        return result

    @app.get("/api/labelmap")
    def get_labelmap():
        return project.labelmap()

    @app.put("/api/labelmap")
    def put_labelmap(payload: dict = Body(...)):
        result, event = project.put_labelmap(field(payload, "base_rev"), field(payload, "parts"),
                                             field(payload, "runs"))
        if event is not None:
            hub.publish(event)
        return result

    @app.get("/api/rig/report")
    def get_rig_report():
        return project.rig_report()

    @app.get("/api/rig/parts/{name}.png")
    def get_part_png(name: str):
        return png(project.part_png(name))

    @app.get("/api/rig/parts/{name}.json")
    def get_part_json(name: str):
        return project.part_json(name)

    # ------------------------------------------------------------ replacement images

    @app.post("/api/swaps/{name}/image")
    def put_swap_image(name: str, file: UploadFile = File(...)):
        return project.put_swap_image(name, file.file.read())

    @app.get("/api/swaps/{name}.png")
    def get_swap_png(name: str, image: str = ""):
        return png(project.swap_png(name))

    # ------------------------------------------------------------ animation

    @app.get("/api/anim")
    def get_anim():
        return project.read_doc("anim")

    @app.put("/api/anim")
    def put_anim(payload: dict = Body(...)):
        result, event = project.put_anim(field(payload, "base_rev"), field(payload, "data"))
        hub.publish(event)
        return result

    @app.delete("/api/anim")
    def delete_anim(base_rev: str | None = None):
        result, event = project.delete_anim(base_rev)
        hub.publish(event)
        return result

    @app.post("/api/anim/preset")
    def apply_preset(payload: dict = Body(...)):
        result, event = project.apply_preset(
            field(payload, "base_rev"), field(payload, "preset"), payload.get("frames"),
            payload.get("fps"), payload.get("duration_ms"))
        hub.publish(event)
        return result

    @app.post("/api/anim/retime")
    def retime(payload: dict = Body(...)):
        result, event = project.retime(field(payload, "base_rev"), payload.get("frames"),
                                       payload.get("fps"), payload.get("duration_ms"))
        hub.publish(event)
        return result

    # ------------------------------------------------------------ render, QA

    @app.get("/api/render/frames/{index}.png")
    def frame_png(index: int, hide: str = "", rig_rev: str = "", anim_rev: str = ""):
        return png(project.frame_png(index, hidden(hide)))

    @app.get("/api/render/frames/{index}.json")
    def frame_json(index: int, hide: str = "", rig_rev: str = "", anim_rev: str = ""):
        return project.frame_json(index, hidden(hide))

    @app.get("/api/report")
    def report():
        return project.report()

    # ------------------------------------------------------------ snapshots, export

    @app.get("/api/snapshots")
    def snapshots():
        return project.snapshots()

    @app.post("/api/snapshots")
    def create_snapshot(payload: dict = Body(default={})):
        return project.create_snapshot((payload or {}).get("label"))

    @app.post("/api/snapshots/{snap_id}/restore")
    def restore_snapshot(snap_id: str):
        hub.publish(*project.restore_snapshot(snap_id))
        try:
            return project.info()
        except ProjectError as exc:
            if exc.status != 404:
                raise
            return {"empty": True}          # the restored version is the one of a folder without project

    @app.get("/api/export/summary")
    def export_summary():
        return project.export_summary()

    @app.post("/api/export")
    def run_export(payload: dict = Body(default={})):
        return project.export((payload or {}).get("formats"))

    # ------------------------------------------------------------ events

    @app.get("/api/events")
    async def events(request: Request):
        queue: asyncio.Queue = asyncio.Queue()
        hub.clients.add(queue)

        async def stream():
            try:
                yield ": connected\n\n"
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), PING_INTERVAL_S)
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    if event is None:           # server shutting down
                        break
                    yield sse_format(event)
            finally:
                hub.clients.discard(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
    def unknown_api(rest: str):
        raise ProjectError(f"Route inconnue : /api/{rest}", 404)

    # ------------------------------------------------------------ the app itself

    @app.get("/")
    def root():
        return RedirectResponse("/index.html?api=/api", status_code=307)

    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir)), name="app")
    return app
