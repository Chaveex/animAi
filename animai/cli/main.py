"""animai CLI entry point. Thin layer over animai.core; no logic here.

Every command prints exactly one JSON object on stdout:
``{"ok": bool, "outputs": {...}, "warnings": [...], "error": null | str}``.
Exit codes: 0 = ok, 1 = user error (or QA failure for ``validate``),
2 = not implemented / internal error.
"""
from __future__ import annotations

import argparse
import json
import sys

from animai.core import pipeline
from animai.core.errors import AnimaiError, NotImplementedFeature

COMMANDS = ["prepare", "inspect", "rig", "animate", "validate", "export", "serve"]


class _Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would print usage and exit(2)
        raise AnimaiError(f"usage error: {message}")


def _crop(text: str) -> tuple[int, int, int, int]:
    parts = text.split(",")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("expected X,Y,W,H")
    try:
        return tuple(int(p) for p in parts)  # type: ignore[return-value]
    except ValueError:
        raise argparse.ArgumentTypeError("expected four integers X,Y,W,H") from None


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="animai", description="Animate pixel art sprites with rigid parts.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("prepare", help="clean a sprite: real pixel scale, binary alpha, palette")
    p.add_argument("input")
    p.add_argument("--out", help="output directory (default: <input stem>.animai next to the input)")
    p.add_argument("--bg", default="auto", help="auto | none | rembg | #RRGGBB (default: auto)")
    p.add_argument("--bg-mode", choices=["flood", "key"], default="flood")
    p.add_argument("--bg-tolerance", type=int, default=0)
    p.add_argument("--alpha-threshold", type=int, default=128)
    p.add_argument("--scale", default="auto",
                   help="auto | integer upscale factor of the input | pixel pitch like 19.6 (non-integer grid)")
    p.add_argument("--max-colors", type=int, default=None)
    p.add_argument("--merge-colors", type=int, default=None, metavar="N",
                   help="merge colours within N per channel (default: 16 if the grid was estimated, else 0)")
    p.add_argument("--zoom", type=int, default=8)

    p = sub.add_parser("inspect", help="zoomed view with pixel grid and coordinates")
    p.add_argument("sprite")
    p.add_argument("--out", help="output .png file or directory (default: inspect.png next to the sprite)")
    p.add_argument("--zoom", type=int, default=8)
    p.add_argument("--crop", type=_crop, default=None, metavar="X,Y,W,H")
    p.add_argument("--segments", action="store_true",
                   help="add outputs.segments: per row, the runs [x0, x1, colour] of the opaque pixels")

    p = sub.add_parser("rig", help="build label map and parts from rig.json, with control images")
    p.add_argument("sprite")
    p.add_argument("rig")
    p.add_argument("--out", help="output directory (default: rig/ next to rig.json)")
    p.add_argument("--zoom", type=int, default=8)
    p.add_argument("--labels", choices=["names", "numbers", "none"], default="names",
                   help="labels on the skeleton overlay (numbers = outputs.bone_numbers)")

    p = sub.add_parser("animate", help="render the frames of a preset or of an anim.json")
    p.add_argument("rig")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--preset", help="name of a preset in animai/presets")
    src.add_argument("--keyframes", help="path to an anim.json")
    p.add_argument("--sprite", help="cleaned sprite (default: rig.sprite, relative to rig.json)")
    p.add_argument("--duration", help="total duration, e.g. 0.8s or 800ms (bare number = seconds)")
    p.add_argument("--frames", type=int)
    p.add_argument("--fps", type=float)
    p.add_argument("--out", help="output directory (default: frames/<name>/ next to rig.json)")
    p.add_argument("--rotation", choices=["rotsprite", "nearest"], default="rotsprite")
    p.add_argument("--padding", type=int, default=2)
    p.add_argument("--gif-scale", type=int, default=4)
    p.add_argument("--mirror", action="store_true", help="flip the animation horizontally (faces left)")
    p.add_argument("--rest-offsets", choices=["on", "off"], default=None,
                   help="apply or ignore the rest offsets of the rig (default: what the animation asks)")

    p = sub.add_parser("validate", help="QA checks on rendered frames, writes report.json")
    p.add_argument("frames_dir")

    p = sub.add_parser("export", help="spritesheet PNG + JSON + GIF")
    p.add_argument("frames_dir")
    p.add_argument("--format", choices=["spritesheet", "godot", "phaser", "unity"], default="spritesheet")
    p.add_argument("--out", help="output directory (default: export/ inside the frames directory)")
    p.add_argument("--columns", type=int, default=None)
    p.add_argument("--gif-scale", type=int, default=4)
    p.add_argument("--mirror", action="store_true", help="flip the exported frames horizontally")

    p = sub.add_parser("serve", help="editor server: API + app, on the local loopback only")
    p.add_argument("project_dir")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--app-dir", help="directory of the web app (default: app/ next to the animai package)")
    p.add_argument("--open", action="store_true", help="open the app in the default browser")
    return parser


def _version() -> str:
    try:
        from importlib.metadata import version
        return version("animai")
    except Exception:
        return "0.1.0"


SERVE_HOST = "127.0.0.1"      # the editor server never listens on another interface


def _serve(args: argparse.Namespace) -> int:
    """Print the usual JSON object once the port is known to be free, then block serving."""
    import socket
    from pathlib import Path

    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        raise AnimaiError(f"project directory not found: {project_dir}")
    try:
        import uvicorn
        from animai.server.app import DEFAULT_APP_DIR, create_app
    except ImportError as exc:
        raise AnimaiError(f"the editor server needs extra packages ({exc.name}); "
                          "run: pip install animai[server]") from exc
    app_dir = Path(args.app_dir) if args.app_dir else DEFAULT_APP_DIR
    warnings = []
    if not (app_dir / "index.html").is_file():
        warnings.append(f"web app not found in {app_dir}: only the API is served (use --app-dir)")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((SERVE_HOST, args.port))
        except OSError as exc:
            raise AnimaiError(f"port {args.port} is not available on {SERVE_HOST}: {exc}") from exc
    url = f"http://{SERVE_HOST}:{args.port}/"
    result = pipeline.Result(outputs={"url": url, "api": url + "api", "host": SERVE_HOST, "port": args.port,
                                      "project_dir": str(project_dir.resolve()), "app_dir": str(app_dir)},
                             warnings=warnings)
    print(json.dumps(result.to_json(), indent=2, ensure_ascii=True), flush=True)
    if args.open:
        import webbrowser
        webbrowser.open(url)
    uvicorn.run(create_app(project_dir, app_dir), host=SERVE_HOST, port=args.port, log_level="warning")
    return 0


def _dispatch(args: argparse.Namespace) -> pipeline.Result:
    if args.command == "prepare":
        return pipeline.run_prepare(args.input, args.out, bg=args.bg, bg_mode=args.bg_mode,
                                    bg_tolerance=args.bg_tolerance, alpha_threshold=args.alpha_threshold,
                                    scale=args.scale, max_colors=args.max_colors, zoom=args.zoom,
                                    merge_colors=args.merge_colors)
    if args.command == "inspect":
        return pipeline.run_inspect(args.sprite, args.out, zoom=args.zoom, crop=args.crop,
                                    segments=args.segments)
    if args.command == "rig":
        return pipeline.run_rig(args.sprite, args.rig, args.out, zoom=args.zoom, labels=args.labels)
    if args.command == "animate":
        return pipeline.run_animate(args.rig, preset=args.preset, keyframes=args.keyframes,
                                    sprite=args.sprite, out_dir=args.out, duration=args.duration,
                                    frames=args.frames, fps=args.fps, rotation=args.rotation,
                                    padding=args.padding, gif_scale=args.gif_scale, mirror=args.mirror,
                                    use_rest_offsets=None if args.rest_offsets is None
                                    else args.rest_offsets == "on")
    if args.command == "validate":
        return pipeline.run_validate(args.frames_dir)
    if args.command == "export":
        return pipeline.run_export(args.frames_dir, args.out, fmt=args.format, columns=args.columns,
                                   gif_scale=args.gif_scale, version=_version(), mirror=args.mirror)
    raise NotImplementedFeature(f"'{args.command}' not implemented")


def main(argv=None) -> int:
    code = 0
    try:
        args = build_parser().parse_args(argv)
        if args.command == "serve":
            return _serve(args)
        result = _dispatch(args)
        if not result.ok:
            code = 1
    except NotImplementedFeature as exc:
        result, code = pipeline.Result(ok=False, error=str(exc)), 2
    except AnimaiError as exc:
        result, code = pipeline.Result(ok=False, error=str(exc)), 1
    except Exception as exc:  # internal error: still one JSON object on stdout
        result, code = pipeline.Result(ok=False, error=f"internal error: {type(exc).__name__}: {exc}"), 2
    print(json.dumps(result.to_json(), indent=2, ensure_ascii=True))
    return code


if __name__ == "__main__":
    sys.exit(main())
