"""A project folder seen as a set of revisioned documents: what the editor server exposes.

The folder on disk is the single source of truth, shared with the CLI and with
whoever edits the files by hand::

    <project>/sprite.png     cleaned sprite (written by ``prepare`` or by an import)
    <project>/palette.json   written with the sprite
    <project>/rig.json
    <project>/anim.json      the one animation edited in the app (optional)
    <project>/frames/<name>/ and <project>/export/   written by an export
    <project>/.animai/snapshots/<id>/                named versions

No HTTP here: the server is a thin mapping of these methods to routes. Errors
are ``ProjectError`` (French message shown as is by the app, with an HTTP-like
status) and ``Conflict`` (write refused because the file changed on disk).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
from pathlib import Path

import numpy as np

from . import export as export_mod
from . import pipeline, qa, render
from .anim import list_presets, load_anim, load_preset, retarget, validate_anim
from .errors import AnimaiError
from .imageio import decode_rgba, dumps_json, encode_png, normalize_rgba, read_json, save_png, write_json
from .messages import classify_all
from .rig import (UNASSIGNED, apply_labelmap_delta, build_label_map, cut_parts, load_rig, normalize_rig,
                  validate_rig)
from .sprite import extract_palette, is_alpha_binary, prepare_sprite, row_segments
from .template import humanoid_template
from .timing import resample

DOCS = {"rig": "rig.json", "anim": "anim.json"}
SPRITE_NAME = "sprite.png"
MAX_IMPORT_SIZE = 512
EXPORT_FORMATS = ["spritesheet", "gif"]
REST_ANIM = {"version": 1, "name": "rest", "loop": False, "fps": 10, "frames": [{"duration_ms": 100}]}


class ProjectError(AnimaiError):
    """Error with an HTTP-like status and a message in French, displayed as is by the app."""

    def __init__(self, message: str, status: int = 422, details=None, *, code: str | None = None,
                 core: BaseException | str | None = None):
        """``code``: stable identifier of the error; ``core``: the message of the core that caused it.

        Both are put in ``details`` (``details.code``, ``details.core_message``) so the
        French sentence and the engine message can be told apart.
        """
        super().__init__(message)
        self.status = status
        if code is not None or core is not None:
            details = dict(details) if isinstance(details, dict) else ({} if details is None else {"data": details})
            if code is not None:
                details["code"] = code
            if core is not None:
                details["core_message"] = str(core)
        self.details = details


class Conflict(Exception):
    """Write refused: the document changed on disk since the revision known by the writer."""

    def __init__(self, info: dict):
        super().__init__(info.get("error", "conflict"))
        self.info = info


def revision(data: bytes) -> str:
    """Opaque revision of a file content (first 16 hex digits of its SHA-1)."""
    return hashlib.sha1(data).hexdigest()[:16]


def diff_paths(a, b, prefix: str = "", limit: int = 50) -> list[str]:
    """Dotted paths of the leaves that differ between two JSON values."""
    out: list[str] = []

    def walk(x, y, path):
        if len(out) >= limit or x == y:
            return
        if isinstance(x, dict) and isinstance(y, dict):
            for key in list(x) + [k for k in y if k not in x]:
                if key not in x or key not in y:
                    if len(out) < limit:
                        out.append(f"{path}.{key}" if path else str(key))
                else:
                    walk(x[key], y[key], f"{path}.{key}" if path else str(key))
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y) and \
                any(isinstance(v, (dict, list)) for v in x + y):
            for i, (u, v) in enumerate(zip(x, y)):
                walk(u, v, f"{path}.{i}" if path else str(i))
        else:
            out.append(path or "(document)")

    walk(a, b, prefix)
    return out


def encode_runs(values: np.ndarray) -> list[list[int]]:
    """Row-by-row run-length encoding of a 2D integer map: ``[[value, length], ...]``."""
    runs: list[list[int]] = []
    for row in values:
        edges = np.flatnonzero(np.diff(row)) + 1
        starts = np.concatenate(([0], edges))
        ends = np.concatenate((edges, [row.size]))
        runs.extend([int(row[s]), int(e - s)] for s, e in zip(starts, ends))
    return runs


def decode_runs(runs, width: int, height: int) -> np.ndarray:
    """Inverse of ``encode_runs`` (runs may also span several rows)."""
    try:
        values = np.array([r[0] for r in runs], dtype=np.int64)
        lengths = np.array([r[1] for r in runs], dtype=np.int64)
    except (TypeError, IndexError, ValueError):
        raise ProjectError("Label map invalide : « runs » doit être une liste de [label, longueur].") from None
    if lengths.size == 0 or (lengths <= 0).any() or int(lengths.sum()) != width * height:
        raise ProjectError(f"Label map invalide : les runs doivent couvrir exactement {width} x {height} pixels.")
    return np.repeat(values, lengths).reshape(height, width)


class Project:
    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.lock = threading.RLock()
        self._app_state: dict[str, tuple] = {}              # doc -> (rev, mtime_ns) of the last app write
        self._seen: dict[str, str | None] = {}              # last revision announced per doc (+ "sprite")
        self._bad: dict[str, tuple] = {}                    # doc -> (stat signature, message) of an invalid file
        self._prepare_warnings: list[str] = []
        self._cache: dict = {}
        for doc in (*DOCS, "sprite"):
            self._seen[doc] = self._disk_rev(doc)

    # ------------------------------------------------------------ files and revisions

    def path(self, doc: str) -> Path:
        return self.root / (SPRITE_NAME if doc == "sprite" else DOCS[doc])

    def _disk_rev(self, doc: str) -> str | None:
        p = self.path(doc)
        try:
            return revision(p.read_bytes())
        except OSError:
            return None

    def _meta(self, doc: str, rev: str) -> dict:
        try:
            at = int(self.path(doc).stat().st_mtime * 1000)
        except OSError:
            at = int(time.time() * 1000)
        return {"rev": rev, "author": "app" if self._app_state.get(doc) == (rev, self._mtime(doc)) else "external",
                "at": at}

    def _mtime(self, doc: str):
        try:
            return self.path(doc).stat().st_mtime_ns
        except OSError:
            return None

    def _mark_app(self, doc: str, rev: str | None) -> None:
        """Remember that the file as it is on disk right now was written by the app.

        Authorship is tied to this exact file state (content and modification
        time): the same bytes written again later by someone else are external.
        """
        if rev is None:
            self._app_state.pop(doc, None)
        else:
            self._app_state[doc] = (rev, self._mtime(doc))

    def read_doc(self, doc: str) -> dict:
        """``{rev, author, at, data}`` of rig.json / anim.json; 404 when absent."""
        with self.lock:
            p = self.path(doc)
            if not p.is_file():
                raise ProjectError(f"{DOCS[doc]} est absent du projet.", 404)
            raw = p.read_bytes()
            try:
                data = json.loads(raw.decode("utf-8-sig"))
            except ValueError as exc:
                raise ProjectError(f"{DOCS[doc]} n'est pas un JSON valide : {exc}", 422, code="json_invalid", core=exc) from None
            return {**self._meta(doc, revision(raw)), "data": data}

    def _check_base(self, doc: str, base_rev, new_data) -> None:
        current = self._disk_rev(doc)
        if base_rev == current:
            return
        info = {"error": f"Conflit sur {DOCS[doc]} : le fichier a changé sur le disque. Rien n'a été écrit.",
                "doc": doc, "rev": current, "author": "external", "at": int(time.time() * 1000),
                "changed_paths": []}
        if current is not None:
            info.update(self._meta(doc, current))
            try:
                info["changed_paths"] = diff_paths(self.read_doc(doc)["data"], new_data)
            except ProjectError:
                pass
        raise Conflict(info)

    def _write(self, doc: str, data) -> dict:
        """Write a document as the app; returns the event to broadcast."""
        raw = dumps_json(data).encode("utf-8")
        rev = revision(raw)
        self.path(doc).write_bytes(raw)
        self._mark_app(doc, rev)
        self._seen[doc] = rev
        self._bad.pop(doc, None)
        return {"type": f"{doc}.changed", **self._meta(doc, rev)}

    # ------------------------------------------------------------ external changes (file watcher)

    def poll_changes(self) -> list[dict]:
        """Events for what changed on disk since the last call (writes made outside the app).

        A document that is not complete valid JSON, or a rig that does not
        validate, emits nothing; the reason is reported by ``info()``.
        """
        events: list[dict] = []
        with self.lock:
            for doc in DOCS:
                p = self.path(doc)
                try:
                    st = p.stat()
                    sig = (st.st_mtime_ns, st.st_size)
                except OSError:
                    sig = None
                if sig is not None and self._bad.get(doc, (None,))[0] == sig:
                    continue
                rev = self._disk_rev(doc)
                if rev == self._seen[doc]:
                    self._bad.pop(doc, None)
                    continue
                if (self._app_state.get(doc) or (None,))[0] != rev:
                    self._app_state.pop(doc, None)      # the app's version is gone from the disk
                if rev is None:
                    self._seen[doc] = None
                    self._bad.pop(doc, None)
                    events.append({"type": f"{doc}.changed", "rev": None, "author": "external",
                                   "at": int(time.time() * 1000)})
                    continue
                try:
                    data = self.read_doc(doc)["data"]
                    if not isinstance(data, dict):
                        raise ProjectError(f"{DOCS[doc]} doit contenir un objet JSON.")
                    if doc == "rig":
                        validate_rig(normalize_rig(data)[0])
                    else:
                        validate_anim(data)
                except AnimaiError as exc:
                    self._bad[doc] = (sig, f"{DOCS[doc]} modifié sur le disque mais invalide, ignoré : {exc}")
                    continue
                self._bad.pop(doc, None)
                self._seen[doc] = rev
                events.append({"type": f"{doc}.changed", **self._meta(doc, rev)})
            sprite_rev = self._disk_rev("sprite")
            if sprite_rev != self._seen["sprite"]:
                self._seen["sprite"] = sprite_rev
                events.append({"type": "project.changed"})
        return events

    # ------------------------------------------------------------ project, sprite

    def _sprite(self) -> tuple[np.ndarray, str]:
        p = self.path("sprite")
        if not p.is_file():
            raise ProjectError("Aucun projet : sprite.png est absent du dossier.", 404)
        raw = p.read_bytes()
        rev = revision(raw)
        key = ("sprite", rev)
        if key not in self._cache:
            try:
                rgba = decode_rgba(raw)
            except AnimaiError as exc:
                raise ProjectError(f"sprite.png est illisible : {exc}", 422, code="sprite_unreadable", core=exc) from None
            if not is_alpha_binary(rgba):
                raise ProjectError("sprite.png n'est pas nettoyé (alpha autre que 0 ou 255) : "
                                   "lancez « animai prepare » ou réimportez l'image.", 422)
            self._put_cache(key, normalize_rgba(rgba))
        return self._cache[key], rev

    def _put_cache(self, key, value) -> None:
        if len(self._cache) > 24:
            for old in list(self._cache)[:8]:
                del self._cache[old]
        self._cache[key] = value

    def info(self) -> dict:
        with self.lock:
            rgba, rev = self._sprite()
            if not self.path("rig").is_file():
                raise ProjectError("Aucun projet : rig.json est absent du dossier.", 404)
            warnings = list(self._prepare_warnings)
            warnings += [msg for _, msg in self._bad.values()]
            try:
                warnings += load_rig(self.path("rig"))[1]
            except AnimaiError as exc:
                warnings.append(f"rig.json invalide : {exc}")
            anim_rev = self._disk_rev("anim")
            return {"name": self.root.name,
                    "sprite": {"width": int(rgba.shape[1]), "height": int(rgba.shape[0]), "rev": rev},
                    "palette": [c for c, _ in extract_palette(rgba)],
                    "prepare": {"warnings": warnings, "warnings_coded": classify_all(warnings)},
                    "presets": list_presets(),
                    "rig": {"rev": self._disk_rev("rig")},
                    "anim": None if anim_rev is None else {"rev": anim_rev}}

    def segments(self, crop=None) -> dict:
        """Opaque pixels of the sprite as runs per row (same as ``animai inspect --segments``)."""
        with self.lock:
            rgba, rev = self._sprite()
            return {"rev": rev, "width": int(rgba.shape[1]), "height": int(rgba.shape[0]),
                    "segments": row_segments(rgba, crop)}

    def diagnostics(self) -> dict:
        """Rigging facts of the current rig (same as the fields of ``animai rig``)."""
        with self.lock:
            rig, rgba, lm, rev = self._rig_and_labels()
            parts = cut_parts(rig, rgba, lm)
            return {"rev": rev, **pipeline.rig_diagnostics(rig, rgba, lm, parts),
                    "parts": {p.name: {"bone": p.bone, "z": p.z, "pixels": p.own_count, "fill": p.fill,
                                       "hidden_pixels": p.extended_count, "missing_pixels": len(p.missing)}
                              for p in parts}}

    def sprite_png(self) -> bytes:
        """The cleaned sprite, re-encoded by the engine encoder (no colour profile, no gamma chunk)."""
        with self.lock:
            return encode_png(self._sprite()[0])

    def import_image(self, data: bytes, view: str = "side") -> list[dict]:
        """``prepare`` an uploaded image, write sprite + palette + template rig, remove anim.json."""
        with self.lock:
            try:
                res = prepare_sprite(decode_rgba(data))
            except AnimaiError as exc:
                raise ProjectError(f"Image refusée : {exc}", 422, code="image_refused", core=exc) from None
            img = res["image"]
            if max(img.shape[0], img.shape[1]) > MAX_IMPORT_SIZE:
                raise ProjectError(f"Image refusée : {img.shape[1]} x {img.shape[0]} px après nettoyage, "
                                   f"le maximum est {MAX_IMPORT_SIZE} px.", 422)
            try:
                rig = humanoid_template(img, view)
                validate_rig(rig)
            except AnimaiError as exc:
                raise ProjectError(f"Image refusée : {exc}", 422, code="image_refused", core=exc) from None
            self.root.mkdir(parents=True, exist_ok=True)
            save_png(self.path("sprite"), img)
            write_json(self.root / "palette.json", pipeline.palette_document(res))
            if self.path("anim").is_file():
                self.path("anim").unlink()
            self._seen["anim"] = None
            self._seen["sprite"] = self._disk_rev("sprite")
            self._prepare_warnings = list(res["warnings"])
            event = self._write("rig", rig)
            return [{"type": "project.changed"}, event]

    # ------------------------------------------------------------ rig, label map

    def _valid_rig(self, data) -> None:
        try:
            if not isinstance(data, dict):
                raise AnimaiError("top-level value must be an object")
            validate_rig(normalize_rig(data)[0])
        except AnimaiError as exc:
            raise ProjectError(f"rig.json invalide : {exc}", 422, code="rig_invalid", core=exc) from None

    def put_rig(self, base_rev, data) -> tuple[dict, dict]:
        with self.lock:
            self._valid_rig(data)
            self._check_base("rig", base_rev, data)
            event = self._write("rig", data)
            return {"rev": event["rev"]}, event

    def _rig_and_labels(self):
        rgba, _ = self._sprite()
        if not self.path("rig").is_file():
            raise ProjectError("rig.json est absent du projet.", 404)
        raw = self.path("rig").read_bytes()
        try:
            rig = load_rig(self.path("rig"))[0]
        except AnimaiError as exc:
            raise ProjectError(f"rig.json invalide : {exc}", 422, code="rig_invalid", core=exc) from None
        return rig, rgba, build_label_map(rig, rgba), revision(raw)

    def labelmap(self) -> dict:
        """One owner per pixel: index in ``parts``, -1 = unassigned or transparent."""
        with self.lock:
            rig, rgba, lm, rev = self._rig_and_labels()
            return {"rev": rev, "width": int(rgba.shape[1]), "height": int(rgba.shape[0]),
                    "parts": lm.part_names, "runs": encode_runs(lm.labels)}

    def put_labelmap(self, base_rev, parts, runs) -> tuple[dict, dict]:
        """Re-encode the regions of every part from a label map and write rig.json."""
        with self.lock:
            rgba, _ = self._sprite()
            current = self.read_doc("rig")
            data = current["data"]
            self._valid_rig(data)
            names = list(data["parts"])
            if not isinstance(parts, list) or any(p not in data["parts"] for p in parts):
                unknown = [p for p in parts if p not in data["parts"]] if isinstance(parts, list) else parts
                raise ProjectError(f"Label map invalide : pièces inconnues dans rig.json : {unknown}.")
            h, w = rgba.shape[:2]
            labels = decode_runs(runs, w, h)
            if labels.min() < -1 or labels.max() >= max(len(parts), 1):
                raise ProjectError("Label map invalide : un label ne correspond à aucune pièce.")
            remap = np.array([names.index(p) for p in parts] + [UNASSIGNED], dtype=np.int16)
            mapped = remap[labels]                       # label -1 picks the last entry
            mapped[rgba[..., 3] == 0] = UNASSIGNED
            try:
                new, changed, full = apply_labelmap_delta(data, rgba, mapped)
            except AnimaiError as exc:
                raise ProjectError("Label map refusée par le moteur.", 422, code="labelmap_invalid", core=exc) from None
            self._check_base("rig", base_rev, new)
            if not changed:         # nothing to write: same revision, no event
                return {"rev": current["rev"], "regions": {n: data["parts"][n].get("region", {}) for n in names},
                        "changed": [], "full_reencode": False}, None
            event = self._write("rig", new)
            return {"rev": event["rev"], "regions": {n: new["parts"][n]["region"] for n in names},
                    "changed": changed, "full_reencode": full}, event

    # ------------------------------------------------------------ animation

    def _valid_anim(self, data) -> None:
        try:
            if not isinstance(data, dict):
                raise AnimaiError("top-level value must be an object")
            validate_anim(data)
        except AnimaiError as exc:
            raise ProjectError(f"anim.json invalide : {exc}", 422, code="anim_invalid", core=exc) from None

    def put_anim(self, base_rev, data) -> tuple[dict, dict]:
        with self.lock:
            self._valid_anim(data)
            self._check_base("anim", base_rev, data)
            event = self._write("anim", data)
            return {"rev": event["rev"]}, event

    def delete_anim(self, base_rev) -> tuple[dict, dict]:
        with self.lock:
            self._check_base("anim", base_rev, None)
            if self.path("anim").is_file():
                self.path("anim").unlink()
            self._seen["anim"] = None
            return {"rev": None}, {"type": "anim.changed", "rev": None, "author": "app",
                                   "at": int(time.time() * 1000)}

    def _timed(self, anim: dict, frames, fps, duration_ms) -> tuple[dict, list[str]]:
        try:
            if frames is None and fps is None and duration_ms is None:
                return anim, []
            out, _, warnings = resample(anim, duration_ms=duration_ms, frames=frames, fps=fps)
            return out, warnings
        except AnimaiError as exc:
            raise ProjectError(f"Durée incohérente : {exc}", 422, code="timing_inconsistent", core=exc) from None

    def apply_preset(self, base_rev, preset, frames=None, fps=None, duration_ms=None) -> tuple[dict, dict]:
        """Write anim.json from a preset (kept whole: bones missing from the rig only give warnings)."""
        with self.lock:
            try:
                anim, warnings = load_preset(str(preset))
                rig = load_rig(self.path("rig"))[0]
                warnings = warnings + retarget(anim, rig)[1]
            except AnimaiError as exc:
                raise ProjectError(f"Preset refusé : {exc}", 422, code="preset_refused", core=exc) from None
            anim, w = self._timed(anim, frames, fps, duration_ms)
            self._check_base("anim", base_rev, anim)
            event = self._write("anim", anim)
            return {"rev": event["rev"], "data": anim, "warnings": warnings + w,
                    "warnings_coded": classify_all(warnings + w)}, event

    def retime(self, base_rev, frames=None, fps=None, duration_ms=None) -> tuple[dict, dict]:
        with self.lock:
            if frames is None and fps is None and duration_ms is None:
                raise ProjectError("Donnez au moins un paramètre parmi frames, fps, duration_ms.")
            data = self.read_doc("anim")["data"]
            self._valid_anim(data)
            anim, warnings = self._timed(data, frames, fps, duration_ms)
            self._check_base("anim", base_rev, anim)
            event = self._write("anim", anim)
            return {"rev": event["rev"], "data": anim, "warnings": warnings,
                    "warnings_coded": classify_all(warnings)}, event

    # ------------------------------------------------------------ render, QA

    def rendered(self, allow_rest: bool = False) -> pipeline.Rendered:
        """The current disk state rendered by the engine, exactly as ``animai animate --keyframes anim.json``."""
        with self.lock:
            rgba, sprite_rev = self._sprite()
            rig_rev, anim_rev = self._disk_rev("rig"), self._disk_rev("anim")
            if rig_rev is None:
                raise ProjectError("rig.json est absent du projet.", 404)
            if anim_rev is None and not allow_rest:
                raise ProjectError("Aucune animation : anim.json est absent du projet.", 404)
            key = ("render", sprite_rev, rig_rev, anim_rev)
            if key not in self._cache:
                try:
                    rig, warnings = load_rig(self.path("rig"))
                    if anim_rev is None:
                        anim, w = json.loads(json.dumps(REST_ANIM)), []
                    else:
                        anim, w = load_anim(self.path("anim"))
                    warnings += w
                    anim, w = retarget(anim, rig)
                    warnings += w
                    anim, indices, w = resample(anim)
                    warnings += w
                    out = pipeline.render_project(rig, rgba, anim, indices)
                except ProjectError:
                    raise
                except AnimaiError as exc:
                    raise ProjectError(f"Rendu impossible : {exc}", 422, code="render_failed", core=exc) from None
                out.warnings = warnings + out.warnings
                self._put_cache(key, out)
            return self._cache[key]

    def _frame(self, index: int) -> pipeline.Rendered:
        out = self.rendered()
        if not 0 <= index < len(out.result.frames):
            raise ProjectError(f"La frame {index} n'existe pas ({len(out.result.frames)} frames).", 404)
        return out

    def frame_png(self, index: int, hide=()) -> bytes:
        """PNG of a frame on the constant canvas; byte-identical to the exported frame when ``hide`` is empty."""
        with self.lock:
            out = self._frame(index)
            if not hide:
                return encode_png(out.result.frames[index])
            layers = [l for l in out.result.layers[index] if l.part not in set(hide)]
            return encode_png(render.finish_frame(out.result, layers))

    def frame_json(self, index: int, hide=()) -> dict:
        with self.lock:
            out = self._frame(index)
            res = out.result
            names = out.labelmap.part_names
            layers = [l for l in res.layers[index] if l.part not in set(hide)]
            owners = render.compose_owners(layers, res.origin, res.canvas, {n: i for i, n in enumerate(names)})
            meta = out.manifest["frames"][index]
            return {"width": res.canvas[0], "height": res.canvas[1],
                    "origin": [-res.origin[0], -res.origin[1]],
                    "joints": {b: v["joint"] for b, v in meta["bones"].items()},
                    "angles": {b: v["angle"] for b, v in meta["bones"].items()},
                    "pivot": list(res.pivot), "duration_ms": meta["duration_ms"],
                    "parts": names, "owners_runs": encode_runs(owners)}

    def report(self) -> dict:
        """QA report of the current disk state (rest pose when there is no animation).

        Same checks as ``animai validate``. Every entry also has ``pixels`` (all
        faulty pixels, at most 500) in **sprite** coordinates, the space the
        editor draws in; ``pixel`` keeps the meaning it has in report.json.
        """
        with self.lock:
            rig, rgba, lm, _ = self._rig_and_labels()
            if not (lm.labels != UNASSIGNED).any():        # freshly imported: no part owns a pixel yet
                report = qa.unrigged_report(lm.unassigned, with_pixels=True)
                report["warnings_coded"] = classify_all(report["warnings"])
                return report
            out = self.rendered(allow_rest=True)
            manifest = dict(out.manifest)
            manifest["source"] = {**manifest["source"], "unassigned_pixels": out.labelmap.unassigned}
            report = qa.validate_frames(out.result.frames, manifest, with_pixels=True)
            ox, oy = out.result.origin
            for check in report["checks"]:
                if check["frame"] is not None:
                    check["pixels"] = [[x + ox, y + oy] for x, y in check["pixels"]]
            report["warnings_coded"] = classify_all(report.get("warnings", []))
            return report

    def rig_report(self) -> dict:
        """Content of rig_report.json for the current disk state, with the rig revision."""
        with self.lock:
            rig, rgba, lm, rev = self._rig_and_labels()
            return {"rev": rev, **pipeline.rig_report(rig, rgba, lm, cut_parts(rig, rgba, lm))}

    def _part(self, name: str):
        rig, rgba, lm, rev = self._rig_and_labels()
        if name not in rig["parts"]:
            raise ProjectError(f"Pièce « {name} » inconnue dans rig.json.", 404, code="part_unknown")
        part = next((p for p in cut_parts(rig, rgba, lm) if p.name == name), None)
        return rig, rgba, part, rev

    def part_png(self, name: str) -> bytes:
        """The part as the engine moves it (own pixels + filled hidden zone), on a sprite-sized canvas."""
        with self.lock:
            _, rgba, part, _ = self._part(name)
            canvas = np.zeros_like(rgba)
            if part is not None:
                h, w = part.image.shape[:2]
                canvas[part.origin[1]:part.origin[1] + h, part.origin[0]:part.origin[0] + w] = part.image
            return encode_png(canvas)

    def part_json(self, name: str) -> dict:
        """Masks of a part on the sprite canvas: ``own_runs`` and ``hidden_runs`` (1 = in the mask)."""
        with self.lock:
            rig, rgba, part, rev = self._part(name)
            own = np.zeros(rgba.shape[:2], dtype=np.int16)
            hidden = np.zeros(rgba.shape[:2], dtype=np.int16)
            spec = rig["parts"][name]
            info = {"rev": rev, "name": name, "bone": spec["bone"], "z": int(spec.get("z", 0)),
                    "width": int(rgba.shape[1]), "height": int(rgba.shape[0]), "fill": "own", "bbox": None,
                    "pixels": 0, "hidden_pixels": 0, "missing": []}
            if part is not None:
                h, w = part.image.shape[:2]
                cut = (slice(part.origin[1], part.origin[1] + h), slice(part.origin[0], part.origin[0] + w))
                own[cut] = part.own_mask
                hidden[cut] = (part.image[..., 3] > 0) & ~part.own_mask
                info.update({"fill": part.fill, "bbox": [part.origin[0], part.origin[1], w, h],
                             "pixels": part.own_count, "hidden_pixels": part.extended_count,
                             "missing": part.missing})
            return {**info, "own_runs": encode_runs(own), "hidden_runs": encode_runs(hidden)}

    # ------------------------------------------------------------ export, snapshots

    def export_summary(self) -> dict:
        with self.lock:
            out = self.rendered()
            m = out.manifest
            return {"canvas": {"width": m["canvas"][0], "height": m["canvas"][1]}, "frames": len(m["frames"]),
                    "duration_ms": m["duration_ms"], "fps": m["fps"], "loop": m["loop"],
                    "pivot": list(m["pivot"]), "name": m["name"], "formats": list(EXPORT_FORMATS)}

    def export(self, formats=None) -> dict:
        """Run animate -> validate -> export of the CLI on the project folder."""
        with self.lock:
            formats = list(formats) if formats else list(EXPORT_FORMATS)
            bad = [f for f in formats if f not in EXPORT_FORMATS]
            if bad:
                known = [f for f in bad if f in export_mod.FORMATS]
                raise ProjectError(f"Format d'export non disponible : {', '.join(map(str, bad))}. "
                                   f"Disponibles : {', '.join(EXPORT_FORMATS)}.", 422,
                                   {"not_implemented": known})
            summary = self.export_summary()
            try:
                animated = pipeline.run_animate(self.path("rig"), keyframes=self.path("anim"),
                                                sprite=self.path("sprite"))
                frames_dir = animated.outputs["frames_dir"]
                validated = pipeline.run_validate(frames_dir)
                exported = pipeline.run_export(frames_dir, self.root / "export")
            except AnimaiError as exc:
                raise ProjectError(f"Export impossible : {exc}", 422, code="export_failed", core=exc) from None
            o = exported.outputs
            outputs = {}
            if "spritesheet" in formats:
                outputs["spritesheet"] = [o["spritesheet"], o["json"]]
            if "gif" in formats:
                outputs["gif"] = [o["gif"]]
            warnings = animated.warnings + exported.warnings
            return {"outputs": outputs, "summary": summary, "warnings": warnings,
                    "warnings_coded": classify_all(warnings),
                    "qa": {"ok": validated.ok, "failed": validated.outputs["failed"],
                           "report": validated.outputs["report"]}}

    def _snap_dir(self) -> Path:
        return self.root / ".animai" / "snapshots"

    def snapshots(self) -> list[dict]:
        out = []
        d = self._snap_dir()
        if d.is_dir():
            for meta in sorted(d.glob("*/meta.json")):
                try:
                    out.append(read_json(meta))
                except AnimaiError:
                    continue
        return out

    def create_snapshot(self, label) -> dict:
        with self.lock:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            n = 0
            while (self._snap_dir() / f"{stamp}-{n}").exists():
                n += 1
            target = self._snap_dir() / f"{stamp}-{n}"
            target.mkdir(parents=True)
            for name in (SPRITE_NAME, "palette.json", *DOCS.values()):
                if (self.root / name).is_file():
                    shutil.copyfile(self.root / name, target / name)
            meta = {"id": target.name, "label": str(label or target.name), "author": "app",
                    "at": int(time.time() * 1000),
                    "empty": not any((target / n).is_file() for n in (SPRITE_NAME, *DOCS.values()))}
            write_json(target / "meta.json", meta)
            return meta

    def restore_snapshot(self, snap_id: str) -> list[dict]:
        with self.lock:
            target = self._snap_dir() / snap_id
            if "/" in snap_id or "\\" in snap_id or ".." in snap_id or not (target / "meta.json").is_file():
                raise ProjectError(f"Version « {snap_id} » introuvable.", 404)
            for name in (SPRITE_NAME, "palette.json", *DOCS.values()):
                if (target / name).is_file():
                    shutil.copyfile(target / name, self.root / name)
                elif (self.root / name).is_file():       # absent from the version: absent after the restore
                    (self.root / name).unlink()
            events = [{"type": "project.changed"}]
            for doc in DOCS:
                rev = self._disk_rev(doc)
                self._mark_app(doc, rev)
                self._seen[doc] = rev
            self._seen["sprite"] = self._disk_rev("sprite")
            return events
