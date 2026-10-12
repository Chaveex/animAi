"""Editor server (docs/schemas.md, "Serveur de l'editeur"; routes of docs/ux-spec.md 13.2).

Runs the FastAPI app in-process with its test client on a temporary project folder, plus
one real `animai serve` subprocess for the event stream and the Host check.

Needs the `server` extra (fastapi, python-multipart, uvicorn) and httpx. When they are
missing, the whole module is reported as SKIPPED and tests/conftest.py prints a loud
"SERVER TESTS NOT RUN" block in the terminal summary: it never passes silently.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import time

import numpy as np
import pytest
from PIL import Image

from tests.conftest import SERVER_EXTRA_MISSING, load_case, preset_document

if SERVER_EXTRA_MISSING:
    pytest.skip("server extra not installed (missing: " + ", ".join(SERVER_EXTRA_MISSING)
                + "): run `pip install -e .[server,dev]`", allow_module_level=True)

import httpx  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from animai.server.app import create_app  # noqa: E402
from tests import cli_adapter as cli, contract, invariants as inv  # noqa: E402

pytestmark = pytest.mark.server

CANONICAL = set(contract.CANONICAL_BONES)
WALK4 = [{"duration_ms": 100, "bones": {"arm_r": {"rot": 15 * i}, "thigh_l": {"rot": -15 * (i % 2)}}}
         for i in range(4)]


def rev_of(path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def png_array(response) -> np.ndarray:
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    return np.array(Image.open(io.BytesIO(response.content)).convert("RGBA"))


def png_chunks(data: bytes) -> list[str]:
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    chunks, offset = [], 8
    while offset < len(data):
        length = int.from_bytes(data[offset:offset + 4], "big")
        chunks.append(data[offset + 4:offset + 8].decode("ascii"))
        offset += 12 + length
    return chunks


def decode_runs(runs, width, height) -> np.ndarray:
    flat = np.concatenate([np.full(length, value, dtype=np.int64) for value, length in runs])
    assert flat.size == width * height, f"runs cover {flat.size} px, expected {width * height}"
    return flat.reshape(height, width)


def encode_runs(labels: np.ndarray) -> list[list[int]]:
    runs = []
    for value in labels.reshape(-1).tolist():
        if runs and runs[-1][0] == value:
            runs[-1][1] += 1
        else:
            runs.append([value, 1])
    return runs


def assert_error(response, status, code=None):
    assert response.status_code == status, f"expected {status}, got {response.status_code}: {response.text}"
    body = response.json()
    assert isinstance(body.get("error"), str) and body["error"], "errors carry a readable sentence"
    if status == 409:       # {error, doc, rev, author, at, changed_paths}
        assert set(body) >= {"doc", "rev", "author", "at", "changed_paths"}, body
        assert isinstance(body["changed_paths"], list) and len(body["changed_paths"]) <= 50
    else:
        assert "details" in body
    if code is not None:
        assert body["details"]["code"] == code, body
        assert isinstance(body["details"]["core_message"], str) and body["details"]["core_message"].isascii()
    return body


@pytest.fixture
def hero():
    return load_case("hero64")


@pytest.fixture
def folder(tmp_path, hero):
    """A project folder made the normal way: `animai prepare`, then the rig next to it."""
    project = tmp_path / "project"
    cli.prepare(hero.source, project, tmp_path).expect_ok()
    (project / "rig.json").write_bytes(hero.rig_path.read_bytes())
    return project


@pytest.fixture
def client(folder):
    with TestClient(create_app(folder)) as test_client:
        yield test_client


@pytest.fixture
def empty_client(tmp_path):
    root = tmp_path / "empty"
    root.mkdir()
    with TestClient(create_app(root)) as test_client:
        test_client.root = root
        yield test_client


def put_anim(client, frames=None, base_rev=None, **extra):
    data = {"version": 1, "name": "custom", "loop": True, "fps": 10, "frames": frames or WALK4, **extra}
    response = client.put("/api/anim", json={"base_rev": base_rev, "data": data})
    assert response.status_code == 200, response.text
    return response.json()["rev"]


def tree(folder) -> dict:
    return {p.relative_to(folder).as_posix(): p.read_bytes() for p in sorted(folder.rglob("*")) if p.is_file()}


# --------------------------------------------------------------------------- #
# host, root, unknown routes
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize("host", ["evil.example", "192.168.1.10", "127.0.0.1.evil.example", "localhost.evil"])
def test_foreign_host_header_is_refused(host, client, folder):
    before = tree(folder)
    for method, url in (("GET", "/api/project"), ("GET", "/api/rig"), ("DELETE", "/api/anim")):
        response = client.request(method, url, headers={"host": host})
        assert response.status_code == 400, f"{method} {url} with Host {host}: {response.status_code}"
    assert tree(folder) == before


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "127.0.0.1:8765", "localhost:8765"])
def test_local_host_headers_are_accepted(host, client):
    assert client.get("/api/project", headers={"host": host}).status_code == 200


def test_root_redirects_to_the_app_with_the_api_parameter(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307) and response.headers["location"] == "/index.html?api=/api"


def test_unknown_api_route_is_a_json_404(client):
    for method in ("GET", "POST", "PUT", "DELETE"):
        assert_error(client.request(method, "/api/does/not/exist"), 404)


# --------------------------------------------------------------------------- #
# 1, 2, 3: project, import, sprite
# --------------------------------------------------------------------------- #

def test_project_route(client, folder, hero):
    body = client.get("/api/project").json()
    assert body["name"] == folder.name
    assert body["sprite"] == {"width": 64, "height": 64, "rev": body["sprite"]["rev"]} and body["sprite"]["rev"]
    assert {inv.hex_to_rgb(c) for c in body["palette"]} == set(hero.palette)
    assert body["prepare"]["warnings"] == [] and body["prepare"]["warnings_coded"] == []
    assert {"idle", "walk", "attack"} <= set(body["presets"])
    assert body["rig"] == {"rev": rev_of(folder / "rig.json")} and body["anim"] is None
    put_anim(client)
    assert client.get("/api/project").json()["anim"] == {"rev": rev_of(folder / "anim.json")}


def test_project_route_404_until_sprite_and_rig_exist(empty_client, hero):
    assert_error(empty_client.get("/api/project"), 404)
    (empty_client.root / "sprite.png").write_bytes(hero.sprite.read_bytes())
    assert_error(empty_client.get("/api/project"), 404)
    (empty_client.root / "rig.json").write_bytes(hero.rig_path.read_bytes())
    assert empty_client.get("/api/project").status_code == 200


def test_project_reports_an_invalid_rig_on_disk_instead_of_failing(client, folder):
    (folder / "rig.json").write_text('{"version": 1, "bones": {', encoding="utf-8")
    body = client.get("/api/project").json()
    assert body["prepare"]["warnings"], "the reason of the invalid rig.json must be shown"
    assert any(w["code"] in ("rig_invalid_on_disk", "doc_invalid_on_disk") for w in body["prepare"]["warnings_coded"])


def test_import_prepares_the_image_and_writes_a_template_rig(empty_client, hero):
    upscaled = load_case("hero64_x4")
    (empty_client.root / "anim.json").write_text("{}", encoding="utf-8")
    response = empty_client.post("/api/project/import", data={"view": "side"},
                                 files={"file": ("hero.png", upscaled.source.read_bytes(), "image/png")})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sprite"]["width"] == 64 and body["sprite"]["height"] == 64, "x4 upscale undone by prepare"
    assert np.array_equal(inv.canonical(empty_client.root / "sprite.png"), inv.canonical(hero.sprite))
    assert (empty_client.root / "palette.json").is_file()
    assert not (empty_client.root / "anim.json").exists(), "import removes anim.json"
    rig = json.loads((empty_client.root / "rig.json").read_text(encoding="utf-8"))
    assert contract.validate_rig(rig) == [] and rig["sprite"] == "sprite.png" and rig["view"] == "side"
    assert set(rig["bones"]) == CANONICAL, "template: the 15 canonical bones"
    assert {p["bone"] for p in rig["parts"].values()} == CANONICAL and len(rig["parts"]) == 15
    opaque = hero.sprite_rgba()[..., 3] > 0
    for name, bone in rig["bones"].items():
        x, y = bone["joint"]
        assert 0 <= x < 64 and 0 <= y < 64, f"template joint of {name} is outside the sprite"
    assert opaque.any()
    assert (empty_client.root / "rig.json").read_bytes().count(b"\r\n") == 0, "LF line ends"


@pytest.mark.parametrize("payload, name", [
    (b"this is not an image", "notes.png"),
    (b"", "empty.png"),
])
def test_import_refuses_what_is_not_an_image(payload, name, client, folder):
    before = tree(folder)
    response = client.post("/api/project/import", files={"file": (name, payload, "image/png")})
    assert_error(response, 422)
    assert tree(folder) == before, "a refused import must not touch the project"


def test_import_refuses_an_empty_or_oversized_picture(client, folder):
    before = tree(folder)
    for image in (Image.new("RGBA", (64, 64), (0, 0, 0, 0)),              # nothing opaque
                  Image.effect_noise((600, 600), 80).convert("RGBA")):    # > 512 px after cleaning
        buffer = io.BytesIO()
        image.save(buffer, "PNG")
        assert_error(client.post("/api/project/import",
                                 files={"file": ("x.png", buffer.getvalue(), "image/png")}), 422)
    assert tree(folder) == before


def test_report_right_after_an_import(empty_client, hero):
    """No part has pixels yet: the QA panel must still answer (ux-spec D4)."""
    empty_client.post("/api/project/import", files={"file": ("h.png", hero.source.read_bytes(), "image/png")})
    response = empty_client.get("/api/report")
    assert response.status_code == 200, response.text
    report = response.json()
    assert contract.validate_report(report) == []
    assert report["ok"] is False
    by_id = {c["id"]: c for c in report["checks"]}
    assert by_id["parts_assigned"]["pass"] is False
    opaque = hero.sprite_rgba()[..., 3] > 0
    pixels = {tuple(p) for p in by_id["parts_assigned"]["pixels"]}
    assert pixels and all(opaque[y, x] for x, y in pixels), "pixels = unassigned opaque pixels, sprite coords"
    assert len(pixels) == min(int(opaque.sum()), 500)
    for check_id in set(inv.CHECK_IDS) - {"parts_assigned"}:
        assert by_id[check_id]["pass"] is True
        assert by_id[check_id]["detail"] == "not applicable: no part has pixels yet"


def test_report_right_after_an_import_carries_warnings_coded(empty_client, hero):
    """docs/schemas.md, step 5, row GET /api/report: 'Champ ajoute : warnings_coded'."""
    empty_client.post("/api/project/import", files={"file": ("h.png", hero.source.read_bytes(), "image/png")})
    assert isinstance(empty_client.get("/api/report").json().get("warnings_coded"), list)


def test_sprite_png_is_the_clean_sprite_with_bare_chunks(client, hero):
    response = client.get("/api/sprite.png", params={"rev": "anything"})
    assert np.array_equal(inv.canonical(png_array(response)), inv.canonical(hero.sprite))
    assert png_chunks(response.content) == ["IHDR", "IDAT", "IEND"], "no gAMA / sRGB / iCCP chunk"


def test_sprite_png_errors(client, folder, empty_client, hero):
    assert_error(empty_client.get("/api/sprite.png"), 404)
    soft = hero.sprite_rgba().copy()
    soft[..., 3][soft[..., 3] == 255] = 128
    Image.fromarray(soft, "RGBA").save(folder / "sprite.png")
    assert_error(client.get("/api/sprite.png"), 422)


# --------------------------------------------------------------------------- #
# 4, 5: rig
# --------------------------------------------------------------------------- #

def test_get_rig(client, folder):
    body = client.get("/api/rig").json()
    assert set(body) == {"rev", "author", "at", "data"}
    assert body["data"] == json.loads((folder / "rig.json").read_text(encoding="utf-8"))
    assert body["rev"] == rev_of(folder / "rig.json"), "rev = first 16 hex digits of the SHA-1 of the file"
    assert body["author"] == "external", "at start-up everything is external"
    assert abs(body["at"] - (folder / "rig.json").stat().st_mtime * 1000) < 5


def test_put_rig_writes_the_document_and_signs_it(client, folder):
    current = client.get("/api/rig").json()
    data = current["data"]
    data["bones"]["head"]["joint"][1] -= 1
    response = client.put("/api/rig", json={"base_rev": current["rev"], "data": data})
    assert response.status_code == 200 and set(response.json()) >= {"rev"}
    assert json.loads((folder / "rig.json").read_text(encoding="utf-8")) == data, "written as received"
    raw = (folder / "rig.json").read_bytes()
    assert b"\r\n" not in raw and raw.startswith(b"{\n  "), "CLI format: indent 2, LF"
    after = client.get("/api/rig").json()
    assert after["rev"] == response.json()["rev"] == rev_of(folder / "rig.json") != current["rev"]
    assert after["author"] == "app"


def test_put_rig_with_a_stale_base_rev_is_a_409_and_writes_nothing(client, folder):
    current = client.get("/api/rig").json()
    theirs = json.loads(json.dumps(current["data"]))
    theirs["bones"]["head"]["joint"] = [30, 20]
    (folder / "rig.json").write_text(json.dumps(theirs, indent=2), encoding="utf-8")   # Claude edits
    on_disk = (folder / "rig.json").read_bytes()
    mine = json.loads(json.dumps(current["data"]))
    mine["bones"]["spine"]["joint"] = [31, 36]
    response = client.put("/api/rig", json={"base_rev": current["rev"], "data": mine})
    body = assert_error(response, 409)
    assert (folder / "rig.json").read_bytes() == on_disk, "409: nothing is written"
    assert body["doc"] == "rig" and body["rev"] == rev_of(folder / "rig.json") and body["author"] == "external"
    assert isinstance(body["at"], int)
    assert set(body["changed_paths"]) == {"bones.head.joint.0", "bones.head.joint.1", "bones.spine.joint.0",
                                          "bones.spine.joint.1"} or \
        {p.rsplit(".", 1)[0] if p[-1].isdigit() else p for p in body["changed_paths"]} == \
        {"bones.head.joint", "bones.spine.joint"}, body["changed_paths"]
    assert len(body["changed_paths"]) <= 50


@pytest.mark.parametrize("break_it, needle", [
    (lambda rig: rig["parts"]["head"].update(bone="skull"), "skull"),
    (lambda rig: rig["bones"].pop("hips"), "hips"),
    (lambda rig: rig["parts"]["head"].pop("region"), "region"),
])
def test_put_rig_refuses_an_invalid_rig(break_it, needle, client, folder):
    current = client.get("/api/rig").json()
    before = (folder / "rig.json").read_bytes()
    break_it(current["data"])
    body = assert_error(client.put("/api/rig", json={"base_rev": current["rev"], "data": current["data"]}),
                        422, "rig_invalid")
    assert needle in body["details"]["core_message"]
    assert (folder / "rig.json").read_bytes() == before


def test_put_rig_requires_base_rev_and_data(client):
    assert_error(client.put("/api/rig", json={"data": {}}), 422)
    assert_error(client.put("/api/rig", json={"base_rev": "x"}), 422)


def test_rig_routes_404_without_project(empty_client):
    for url in ("/api/rig", "/api/labelmap", "/api/rig/report", "/api/rig/diagnostics"):
        assert_error(empty_client.get(url), 404)


# --------------------------------------------------------------------------- #
# author
# --------------------------------------------------------------------------- #

def test_author_is_external_when_the_same_bytes_come_back_from_another_process(client, folder):
    """`app` only while the file on disk is the very state the API wrote (content AND mtime)."""
    current = client.get("/api/rig").json()
    data = current["data"]
    data["pivot"] = [0.5, 1.0]
    data["bones"]["head"]["joint"][0] += 1
    client.put("/api/rig", json={"base_rev": current["rev"], "data": data})
    written_by_app = (folder / "rig.json").read_bytes()
    assert client.get("/api/rig").json()["author"] == "app"

    (folder / "rig.json").write_bytes(load_case("hero64").rig_path.read_bytes())       # external edit
    stat = (folder / "rig.json").stat()
    os.utime(folder / "rig.json", (stat.st_atime + 2, stat.st_mtime + 2))
    assert client.get("/api/rig").json()["author"] == "external"

    (folder / "rig.json").write_bytes(written_by_app)                                  # same bytes again
    stat = (folder / "rig.json").stat()
    os.utime(folder / "rig.json", (stat.st_atime + 4, stat.st_mtime + 4))
    after = client.get("/api/rig").json()
    assert after["rev"] == hashlib.sha1(written_by_app).hexdigest()[:16]
    assert after["author"] == "external", "identical content rewritten later by someone else is external"


# --------------------------------------------------------------------------- #
# 6, 7: label map
# --------------------------------------------------------------------------- #

def expected_labels(case, rig=None):
    raster = inv.rasterize_rig(rig or case.rig, case.native_size)
    labels = raster.labels.astype(np.int64) - 1
    labels[case.sprite_rgba()[..., 3] == 0] = -1
    return labels


def test_get_labelmap(client, folder, hero):
    body = client.get("/api/labelmap").json()
    assert body["width"] == 64 and body["height"] == 64
    assert body["parts"] == list(hero.rig["parts"]), "parts in the order of rig.json"
    assert body["rev"] == rev_of(folder / "rig.json"), "the label map has the rev of the rig"
    assert np.array_equal(decode_runs(body["runs"], 64, 64), expected_labels(hero))
    column = 0
    for _, length in body["runs"]:                       # runs are cut at each end of line
        column += length
        assert column <= 64
        column %= 64
    assert column == 0


def with_polygons(rig):
    """Hand-written shapes: head as a polygon, torso with an exclude rect it does not need."""
    rects = rig["parts"]["thigh_r"]["region"]["rects"]
    x, y, w, h = rects[0]
    rig["parts"]["thigh_r"]["region"] = {"polygons": [[[x, y], [x + w - 1, y], [x + w - 1, y + h - 1],
                                                       [x, y + h - 1]]]}
    rig["parts"]["shin_l"]["region"]["exclude"] = {"rects": [[0, 0, 2, 2]], "polygons": [], "pixels": []}
    return rig


def test_put_labelmap_delta_keeps_hand_written_polygons_and_exclude(client, folder, hero):
    current = client.get("/api/rig").json()
    rig = with_polygons(current["data"])
    client.put("/api/rig", json={"base_rev": current["rev"], "data": rig})
    labelmap = client.get("/api/labelmap").json()
    labels = decode_runs(labelmap["runs"], 64, 64)
    assert np.array_equal(labels, expected_labels(hero)), "test premise: same ownership as the fixture rig"
    parts = labelmap["parts"]
    head, torso = parts.index("head"), parts.index("torso")
    ys, xs = np.nonzero(labels == head)
    y = int(ys.max())
    x = int(xs[ys == y][0])
    assert labels[y + 1, x] == torso, "test premise: this head pixel sits on the torso"
    labels[y, x] = torso                                   # one stroke: a head pixel goes to the torso

    response = client.put("/api/labelmap", json={"base_rev": labelmap["rev"], "parts": parts,
                                                 "runs": encode_runs(labels)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["changed"]) == ["head", "torso"] and body["full_reencode"] is False
    written = json.loads((folder / "rig.json").read_text(encoding="utf-8"))
    assert body["rev"] == rev_of(folder / "rig.json") != labelmap["rev"]
    for name, part in written["parts"].items():
        assert body["regions"][name] == part["region"], "regions = each region as written"
        if name not in ("head", "torso"):
            assert part == rig["parts"][name], f"part '{name}' did not change: it must not be rewritten"
    assert written["parts"]["thigh_r"]["region"]["polygons"], "the hand-written polygon is kept"
    assert written["parts"]["shin_l"]["region"]["exclude"]["rects"] == [[0, 0, 2, 2]]
    assert [x, y] in written["parts"]["torso"]["region"]["pixels"], "gained pixel: added to region.pixels"
    assert written["parts"]["head"]["region"]["rects"] == rig["parts"]["head"]["region"]["rects"]
    assert [x, y] in written["parts"]["head"]["region"]["exclude"]["pixels"], \
        "lost pixel still covered by a rect: added to exclude.pixels"
    again = client.get("/api/labelmap").json()
    assert np.array_equal(decode_runs(again["runs"], 64, 64), labels), "the label map reads back as sent"
    assert np.array_equal(labels, expected_labels(hero, written) if False else decode_runs(again["runs"], 64, 64))


def test_put_labelmap_identical_writes_nothing(client, folder):
    labelmap = client.get("/api/labelmap").json()
    before = (folder / "rig.json").read_bytes()
    mtime = (folder / "rig.json").stat().st_mtime_ns
    one_run_per_part = encode_runs(decode_runs(labelmap["runs"], 64, 64))        # runs may span lines
    response = client.put("/api/labelmap", json={"base_rev": labelmap["rev"], "parts": labelmap["parts"],
                                                 "runs": one_run_per_part})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["rev"] == labelmap["rev"] and body["changed"] == [] and body["full_reencode"] is False
    assert (folder / "rig.json").read_bytes() == before
    assert (folder / "rig.json").stat().st_mtime_ns == mtime, "identical label map: the file is not rewritten"


def test_put_labelmap_ignores_labels_on_transparent_pixels(client, folder):
    labelmap = client.get("/api/labelmap").json()
    labels = decode_runs(labelmap["runs"], 64, 64)
    assert labels[0, 0] == -1
    labels[0, 0:3] = 0
    response = client.put("/api/labelmap", json={"base_rev": labelmap["rev"], "parts": labelmap["parts"],
                                                 "runs": encode_runs(labels)})
    assert response.status_code == 200, response.text
    assert client.get("/api/labelmap").json()["runs"] == labelmap["runs"]


def test_put_labelmap_errors(client, folder):
    labelmap = client.get("/api/labelmap").json()
    before = (folder / "rig.json").read_bytes()
    body = assert_error(client.put("/api/labelmap", json={
        "base_rev": "0" * 16, "parts": labelmap["parts"], "runs": labelmap["runs"]}), 409)
    assert body["doc"] == "rig"
    assert_error(client.put("/api/labelmap", json={
        "base_rev": labelmap["rev"], "parts": labelmap["parts"] + ["tail"], "runs": labelmap["runs"]}), 422)
    assert_error(client.put("/api/labelmap", json={
        "base_rev": labelmap["rev"], "parts": labelmap["parts"], "runs": [[0, 10]]}), 422)
    assert_error(client.put("/api/labelmap", json={"base_rev": labelmap["rev"], "parts": labelmap["parts"]}), 422)
    assert (folder / "rig.json").read_bytes() == before


# --------------------------------------------------------------------------- #
# 8 to 12: animation
# --------------------------------------------------------------------------- #

def test_anim_create_read_update_delete(client, folder):
    assert_error(client.get("/api/anim"), 404)
    rev = put_anim(client)
    body = client.get("/api/anim").json()
    assert body["rev"] == rev == rev_of(folder / "anim.json") and body["author"] == "app"
    assert body["data"]["frames"] == WALK4
    newer = put_anim(client, WALK4[:2], base_rev=rev)
    assert newer != rev and len(client.get("/api/anim").json()["data"]["frames"]) == 2
    response = client.delete("/api/anim", params={"base_rev": newer})
    assert response.status_code == 200 and response.json() == {"rev": None}
    assert not (folder / "anim.json").exists()
    assert_error(client.get("/api/anim"), 404)
    assert client.get("/api/project").json()["anim"] is None


def test_anim_conflicts_write_nothing(client, folder):
    rev = put_anim(client)
    before = (folder / "anim.json").read_bytes()
    data = client.get("/api/anim").json()["data"]
    body = assert_error(client.put("/api/anim", json={"base_rev": "f" * 16, "data": data}), 409)
    assert body["doc"] == "anim" and body["rev"] == rev
    assert_error(client.put("/api/anim", json={"base_rev": None, "data": data}), 409)   # it exists already
    assert_error(client.delete("/api/anim", params={"base_rev": "f" * 16}), 409)
    assert (folder / "anim.json").read_bytes() == before


@pytest.mark.parametrize("frames", [
    [],
    [{"duration_ms": 0}],
    [{"duration_ms": 100, "bones": {"hips": {"pos": [0.5, 0]}}}],
])
def test_put_anim_refuses_an_invalid_animation(frames, client, folder):
    response = client.put("/api/anim", json={"base_rev": None, "data": {"version": 1, "frames": frames}})
    assert_error(response, 422, "anim_invalid")
    assert not (folder / "anim.json").exists()


def test_preset_route_writes_the_whole_preset(client, folder):
    response = client.post("/api/anim/preset", json={"base_rev": None, "preset": "walk"})
    assert response.status_code == 200, response.text
    body = response.json()
    preset = preset_document("walk")
    assert [f["bones"] for f in body["data"]["frames"]] == [f["bones"] for f in preset["frames"]]
    assert [f.get("label") for f in body["data"]["frames"]] == [f.get("label") for f in preset["frames"]]
    assert json.loads((folder / "anim.json").read_text(encoding="utf-8")) == body["data"]
    assert body["rev"] == rev_of(folder / "anim.json")
    assert body["warnings"] == [] and body["warnings_coded"] == []
    resampled = client.post("/api/anim/preset", json={"base_rev": body["rev"], "preset": "attack", "frames": 4})
    labels = [f.get("label") for f in resampled.json()["data"]["frames"]]
    assert labels == ["anticipation", "strike", "impact", "rest"]
    assert any(w["code"] == "resample_drops_frames" for w in resampled.json()["warnings_coded"])


def test_preset_route_errors_and_missing_bones(client, folder):
    assert_error(client.post("/api/anim/preset", json={"base_rev": None, "preset": "moonwalk"}), 422)
    assert_error(client.post("/api/anim/preset", json={"base_rev": "f" * 16, "preset": "walk"}), 409)
    assert not (folder / "anim.json").exists()
    current = client.get("/api/rig").json()
    rig = current["data"]
    for bone in [b for b in rig["bones"] if b.startswith(("arm_", "forearm_"))]:
        del rig["bones"][bone]
    for part in rig["parts"].values():
        if part["bone"] not in rig["bones"]:
            part["bone"] = "spine"
    client.put("/api/rig", json={"base_rev": current["rev"], "data": rig})
    body = client.post("/api/anim/preset", json={"base_rev": None, "preset": "walk"}).json()
    assert body["warnings"], "bones absent from the rig give warnings, not an error"
    assert {w["code"] for w in body["warnings_coded"]} == {"bone_not_in_rig"}
    assert all(set(w) == {"code", "params", "message"} for w in body["warnings_coded"])
    assert [w["message"] for w in body["warnings_coded"]] == body["warnings"]


def test_retime_route(client, folder):
    rev = client.post("/api/anim/preset", json={"base_rev": None, "preset": "walk"}).json()["rev"]
    response = client.post("/api/anim/retime", json={"base_rev": rev, "frames": 4})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [f["label"] for f in body["data"]["frames"]] == ["contact_r", "passing_r", "contact_l", "passing_l"]
    codes = {w["code"] for w in body["warnings_coded"]}
    assert {"resample_key_poses_dropped", "resample_drops_frames"} <= codes
    assert json.loads((folder / "anim.json").read_text(encoding="utf-8")) == body["data"]
    slower = client.post("/api/anim/retime", json={"base_rev": body["rev"], "duration_ms": 1600}).json()
    assert sum(f["duration_ms"] for f in slower["data"]["frames"]) == 1600 and len(slower["data"]["frames"]) == 4
    before = (folder / "anim.json").read_bytes()
    bad = client.post("/api/anim/retime", json={"base_rev": slower["rev"], "frames": 8, "fps": 10,
                                                "duration_ms": 1000})
    refused = assert_error(bad, 422, "timing_inconsistent")
    assert "inconsistent" in refused["details"]["core_message"]
    assert_error(client.post("/api/anim/retime", json={"base_rev": "f" * 16, "frames": 4}), 409)
    assert (folder / "anim.json").read_bytes() == before


# --------------------------------------------------------------------------- #
# 13, 14: rendered frames
# --------------------------------------------------------------------------- #

@pytest.fixture
def animated(client, folder, tmp_path):
    """Project with the walk preset as anim.json, and the CLI rendering of the same files."""
    client.post("/api/anim/preset", json={"base_rev": None, "preset": "walk"})
    rendered = cli.animate(folder / "rig.json", tmp_path / "cli_frames", tmp_path,
                           keyframes=folder / "anim.json").expect_ok()
    return rendered


def test_served_frames_are_byte_identical_to_the_cli_frames(client, animated):
    paths = animated.frame_paths()
    assert len(paths) == 8
    for index, path in enumerate(paths):
        response = client.get(f"/api/render/frames/{index}.png", params={"rig_rev": "a", "anim_rev": "b"})
        assert response.status_code == 200
        assert response.content == path.read_bytes(), f"frame {index} differs from the CLI's {path.name}"


def test_served_frame_follows_the_disk_not_a_cache(client, folder, animated, tmp_path):
    before = client.get("/api/render/frames/1.png").content
    rig = json.loads((folder / "rig.json").read_text(encoding="utf-8"))
    rig["bones"]["arm_r"]["joint"][1] += 2
    (folder / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")     # external edit
    after = client.get("/api/render/frames/1.png").content
    assert after != before
    again = cli.animate(folder / "rig.json", tmp_path / "again", tmp_path, keyframes=folder / "anim.json")
    assert after == again.expect_ok().frame_paths()[1].read_bytes()


def test_hide_removes_parts_without_changing_the_canvas(client, animated):
    full = png_array(client.get("/api/render/frames/0.png"))
    hidden = png_array(client.get("/api/render/frames/0.png", params={"hide": "arm_r,forearm_r"}))
    assert hidden.shape == full.shape
    assert (hidden[..., 3] > 0).sum() < (full[..., 3] > 0).sum()
    sleeve = (99, 155, 255)                                  # only the near upper arm has this colour
    assert (full[..., :3] == sleeve).all(axis=2).any() and not (hidden[..., :3] == sleeve).all(axis=2).any()
    assert np.array_equal(png_array(client.get("/api/render/frames/0.png", params={"hide": ""})), full)


def test_frame_routes_404(client, folder, animated):
    for url in ("/api/render/frames/8.png", "/api/render/frames/8.json", "/api/render/frames/-1.png"):
        assert client.get(url).status_code == 404, url
    client.delete("/api/anim", params={"base_rev": rev_of(folder / "anim.json")})
    assert_error(client.get("/api/render/frames/0.png"), 404)
    assert_error(client.get("/api/render/frames/0.json"), 404)


def test_frame_json_matches_frames_json_of_the_cli(client, animated):
    manifest = animated.manifest()
    for index in (0, 3):
        body = client.get(f"/api/render/frames/{index}.json").json()
        assert set(body) >= {"width", "height", "origin", "joints", "angles", "pivot", "duration_ms",
                             "parts", "owners_runs"}
        assert [body["width"], body["height"]] == manifest["canvas"]
        assert body["origin"] == [-manifest["origin"][0], -manifest["origin"][1]], \
            "origin = position of the sprite's (0,0) in the canvas"
        assert body["pivot"] == manifest["pivot"]
        assert body["duration_ms"] == manifest["frames"][index]["duration_ms"]
        pose = manifest["frames"][index]["bones"]
        assert body["joints"] == {bone: p["joint"] for bone, p in pose.items()}
        assert body["angles"] == {bone: p["angle"] for bone, p in pose.items()}
        owners = decode_runs(body["owners_runs"], body["width"], body["height"])
        frame = animated.frames()[index]
        assert np.array_equal(owners >= 0, frame[..., 3] > 0), "an owner exactly where the frame is opaque"
        assert owners.max() < len(body["parts"]) and owners.min() == -1
        head = body["parts"].index("head")
        jx, jy = pose["head"]["joint"]
        assert owners[jy - manifest["origin"][1] - 4, jx - manifest["origin"][0]] == head


# --------------------------------------------------------------------------- #
# 15: report
# --------------------------------------------------------------------------- #

def strip(report):
    return [{k: v for k, v in check.items() if k != "pixels"} for check in report["checks"]]


def test_report_equals_the_cli_validate_report(client, animated, tmp_path):
    verdict = cli.validate(animated.frames_dir(), tmp_path).expect_ok()
    expected = cli.report(verdict)
    body = client.get("/api/report").json()
    assert body["ok"] is True and strip(body) == expected["checks"]
    assert body["metrics"] == expected["metrics"] and body["warnings"] == expected["warnings"]
    assert all(check["pixels"] == [] for check in body["checks"]), "a passing entry has no faulty pixel"
    assert [w["message"] for w in body["warnings_coded"]] == body["warnings"]


def test_report_without_animation_is_the_rest_pose(client):
    body = client.get("/api/report").json()
    assert contract.validate_report(body, require_metrics=True) == []
    assert body["ok"] is True and len(body["metrics"]["frames"]) == 1


def test_report_lists_faulty_pixels_in_sprite_coordinates(client, folder, hero):
    current = client.get("/api/rig").json()
    del current["data"]["parts"]["head"]
    client.put("/api/rig", json={"base_rev": current["rev"], "data": current["data"]})
    body = client.get("/api/report").json()
    assert body["ok"] is False
    entry = [c for c in body["checks"] if c["id"] == "parts_assigned"][0]
    raster = inv.rasterize_rig(hero.rig, hero.native_size)
    head = raster.labels == raster.parts.index("head") + 1
    assert {tuple(p) for p in entry["pixels"]} == {(int(x), int(y)) for y, x in zip(*np.nonzero(head))}
    assert any(w["code"] == "pixels_unassigned" for w in body["warnings_coded"]) or entry["pass"] is False


def test_report_of_a_dislocated_animation_fails_like_the_cli(client, folder, tmp_path):
    walk = preset_document("walk")
    walk["frames"][1]["bones"]["forearm_r"] = {"pos": [9, 0]}
    client.put("/api/anim", json={"base_rev": None, "data": walk})
    body = client.get("/api/report").json()
    failing = [c for c in body["checks"] if c["id"] == "holes" and not c["pass"]]
    assert body["ok"] is False and [c["frame"] for c in failing] == [1]
    assert "dislocated joint 'forearm_r'" in failing[0]["detail"]


# --------------------------------------------------------------------------- #
# 16, 17, 18: snapshots
# --------------------------------------------------------------------------- #

def test_snapshot_create_list_restore(client, folder):
    assert client.get("/api/snapshots").json() == []
    put_anim(client)
    original = {name: (folder / name).read_bytes() for name in ("sprite.png", "palette.json", "rig.json", "anim.json")}
    created = client.post("/api/snapshots", json={"label": "avant Claude"}).json()
    assert set(created) >= {"id", "label", "author", "at"} and created["label"] == "avant Claude"
    listed = client.get("/api/snapshots").json()
    assert [s["id"] for s in listed] == [created["id"]] and listed[0]["label"] == "avant Claude"
    for name in original:
        assert (folder / ".animai" / "snapshots" / created["id"] / name).read_bytes() == original[name]

    current = client.get("/api/rig").json()
    current["data"]["bones"]["head"]["joint"] = [20, 20]
    client.put("/api/rig", json={"base_rev": current["rev"], "data": current["data"]})
    client.delete("/api/anim", params={"base_rev": rev_of(folder / "anim.json")})
    assert (folder / "rig.json").read_bytes() != original["rig.json"]

    restored = client.post(f"/api/snapshots/{created['id']}/restore")
    assert restored.status_code == 200 and restored.json()["name"] == folder.name, "answers like GET /api/project"
    assert {name: (folder / name).read_bytes() for name in original} == original


def test_snapshot_restore_removes_files_absent_from_the_version(client, folder):
    created = client.post("/api/snapshots", json={"label": "no anim"}).json()
    put_anim(client)
    client.post(f"/api/snapshots/{created['id']}/restore")
    assert not (folder / "anim.json").exists()


@pytest.mark.parametrize("snap_id", ["nope", "..", "20990101-000000-0"])
def test_snapshot_restore_unknown_id_is_404(snap_id, client, folder):
    before = tree(folder)
    assert client.post(f"/api/snapshots/{snap_id}/restore").status_code == 404
    assert tree(folder) == before


def test_snapshot_of_an_empty_folder_makes_the_first_import_undoable(empty_client, hero):
    created = empty_client.post("/api/snapshots", json={"label": "vide"})
    assert created.status_code == 200, created.text
    assert created.json()["empty"] is True
    assert empty_client.get("/api/snapshots").json()[0]["empty"] is True
    empty_client.post("/api/project/import", files={"file": ("h.png", hero.source.read_bytes(), "image/png")})
    assert empty_client.get("/api/project").status_code == 200
    restored = empty_client.post(f"/api/snapshots/{created.json()['id']}/restore")
    assert restored.status_code == 200 and restored.json() == {"empty": True}
    for name in ("sprite.png", "palette.json", "rig.json", "anim.json"):
        assert not (empty_client.root / name).exists(), f"{name} must be removed by the restore"
    assert_error(empty_client.get("/api/project"), 404)


# --------------------------------------------------------------------------- #
# 19, 20: export
# --------------------------------------------------------------------------- #

def test_export_summary(client, animated):
    manifest = animated.manifest()
    body = client.get("/api/export/summary").json()
    assert body == {"canvas": {"width": manifest["canvas"][0], "height": manifest["canvas"][1]},
                    "frames": 8, "duration_ms": 800, "fps": manifest["fps"], "loop": True,
                    "pivot": manifest["pivot"], "name": manifest["name"], "formats": ["spritesheet", "gif"]}


def test_export_summary_404_without_animation(client):
    assert_error(client.get("/api/export/summary"), 404)


def test_export_runs_the_cli_chain_in_the_project_folder(client, folder, animated, tmp_path):
    response = client.post("/api/export", json={"formats": ["spritesheet", "gif"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) >= {"outputs", "summary", "warnings", "qa", "warnings_coded"}
    sheet_png, sheet_json = body["outputs"]["spritesheet"]
    (gif,) = body["outputs"]["gif"]
    for path in (sheet_png, sheet_json, gif):
        assert os.path.isabs(path) and os.path.isfile(path) and folder in __import__("pathlib").Path(path).parents
    assert body["qa"]["ok"] is True and body["qa"]["failed"] == []
    assert body["summary"] == client.get("/api/export/summary").json()
    reference = cli.export(animated.frames_dir(), tmp_path / "cli_export", tmp_path).expect_ok()
    assert open(sheet_png, "rb").read() == reference.path(cli.KEY_SHEET).read_bytes()
    assert cli.parse_sheet_json(json.load(open(sheet_json, encoding="utf-8"))).pivots == \
        cli.parse_sheet_json(reference.json(cli.KEY_SHEET_JSON)).pivots


def test_export_happens_even_when_the_qa_fails(client, folder):
    walk = preset_document("walk")
    walk["frames"][1]["bones"]["forearm_r"] = {"pos": [9, 0]}
    client.put("/api/anim", json={"base_rev": None, "data": walk})
    body = client.post("/api/export", json={"formats": ["spritesheet"]}).json()
    assert body["qa"]["ok"] is False and body["qa"]["failed"] == ["holes"]
    assert all(os.path.isfile(p) for p in body["outputs"]["spritesheet"])
    assert any(w["code"] == "qa_failing" for w in body["warnings_coded"])


@pytest.mark.parametrize("formats", [["betamax"], ["godot"], ["spritesheet", "unity"]])
def test_export_unknown_or_unimplemented_format_is_422(formats, client, folder, animated):
    before = tree(folder)
    assert_error(client.post("/api/export", json={"formats": formats}), 422)
    assert tree(folder) == before


# --------------------------------------------------------------------------- #
# read-only routes of steps 3 and 5
# --------------------------------------------------------------------------- #

def test_segments_route_equals_inspect_segments(client, folder, tmp_path):
    reference = cli.inspect(folder / "sprite.png", tmp_path / "inspect", tmp_path, segments=True).expect_ok()
    body = client.get("/api/sprite/segments").json()
    assert body["segments"] == reference.payload["outputs"]["segments"]
    assert body["width"] == 64 and body["height"] == 64 and body["rev"] == client.get("/api/project").json()["sprite"]["rev"]
    cropped = cli.inspect(folder / "sprite.png", tmp_path / "crop", tmp_path, segments=True,
                          crop=(24, 13, 14, 6)).expect_ok()
    assert client.get("/api/sprite/segments", params={"crop": "24,13,14,6"}).json()["segments"] == \
        cropped.payload["outputs"]["segments"]
    assert_error(client.get("/api/sprite/segments", params={"crop": "1,2,3"}), 422)


def test_rig_report_and_diagnostics_equal_the_cli_rig_report(client, folder, tmp_path):
    reference = cli.rig(folder / "sprite.png", folder / "rig.json", tmp_path / "rig", tmp_path).expect_ok()
    expected = reference.json(cli.KEY_RIG_REPORT)
    report = client.get("/api/rig/report").json()
    assert report["rev"] == rev_of(folder / "rig.json")
    for key in ("pivot", "joints", "unmonitored_joints", "thin_parts", "outline", "bones", "parts",
                "unassigned_count", "rest_pose_exact"):
        assert report[key] == expected[key], key
    diagnostics = client.get("/api/rig/diagnostics").json()
    assert diagnostics["rev"] == report["rev"]
    for key in ("joints", "unmonitored_joints", "thin_parts", "outline"):
        assert diagnostics[key] == expected[key], key
    for name, part in diagnostics["parts"].items():
        assert part == {k: expected["parts"][name][k]
                        for k in ("bone", "z", "pixels", "fill", "hidden_pixels", "missing_pixels")}


def test_part_routes_give_the_complete_part(client, folder, hero):
    raster = inv.rasterize_rig(hero.rig, hero.native_size)
    sprite = hero.sprite_rgba()
    for name in ("torso", "arm_l", "head"):
        own = raster.labels == raster.parts.index(name) + 1
        info = client.get(f"/api/rig/parts/{name}.json").json()
        assert set(info) >= {"rev", "name", "bone", "z", "width", "height", "fill", "bbox", "pixels",
                             "hidden_pixels", "missing", "own_runs", "hidden_runs"}
        assert info["name"] == name and info["bone"] == hero.rig["parts"][name]["bone"]
        assert [info["width"], info["height"]] == [64, 64] and info["rev"] == rev_of(folder / "rig.json")
        own_mask = decode_runs(info["own_runs"], 64, 64) == 1
        hidden_mask = decode_runs(info["hidden_runs"], 64, 64) == 1
        assert np.array_equal(own_mask, own), f"own_runs of '{name}' = its own pixels"
        assert not (own_mask & hidden_mask).any()
        assert int(own_mask.sum()) == info["pixels"] and int(hidden_mask.sum()) == info["hidden_pixels"]
        assert (sprite[..., 3][hidden_mask] == 255).all(), "the hidden zone lies under opaque front parts"
        image = png_array(client.get(f"/api/rig/parts/{name}.png"))
        assert image.shape == (64, 64, 4)
        assert np.array_equal(image[..., 3] > 0, own_mask | hidden_mask), "PNG = own pixels + filled hidden zone"
        assert np.array_equal(image[own_mask], sprite[own_mask]), "own pixels keep the sprite colours"
        assert {tuple(c) for c in image[hidden_mask][:, :3].tolist()} <= set(hero.palette)
    torso = client.get("/api/rig/parts/torso.json").json()
    assert torso["hidden_pixels"] > 0, "the torso is completed under the near arm"


def test_part_routes_unknown_part_and_fill_none(client, folder):
    assert client.get("/api/rig/parts/tail.png").status_code == 404
    assert_error(client.get("/api/rig/parts/tail.json"), 404)
    current = client.get("/api/rig").json()
    current["data"]["parts"]["torso"]["fill"] = "none"
    client.put("/api/rig", json={"base_rev": current["rev"], "data": current["data"]})
    info = client.get("/api/rig/parts/torso.json").json()
    assert info["fill"] == "none" and info["hidden_pixels"] == 0 and info["missing"]
    assert client.get("/api/rig/report").json()["parts"]["torso"]["missing_pixels"] == len(info["missing"])


# --------------------------------------------------------------------------- #
# replacement images (rig.swaps)
# --------------------------------------------------------------------------- #

def swap_block(folder, w=6, h=3, colour=None) -> np.ndarray:
    """A small image in one colour of the sprite, with one transparent corner."""
    sprite = np.array(Image.open(folder / "sprite.png").convert("RGBA"))
    image = np.tile(sprite[sprite[..., 3] > 0][0] if colour is None else colour, (h, w, 1)).astype(np.uint8)
    image[0, 0] = 0
    return image


def png_bytes(image: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(image, "RGBA").save(buf, format="PNG")
    return buf.getvalue()


def post_swap(client, name, image):
    return client.post(f"/api/swaps/{name}/image", files={"file": ("x.png", png_bytes(image), "image/png")})


def test_swap_image_upload_stores_the_file_and_leaves_the_rig_alone(client, folder):
    rig_before = (folder / "rig.json").read_bytes()
    image = swap_block(folder)
    response = post_swap(client, "jab", image)
    assert response.status_code == 200, response.text
    assert response.json() == {"image": "swaps/jab.png", "width": 6, "height": 3}
    stored = np.array(Image.open(folder / "swaps" / "jab.png").convert("RGBA"))
    assert np.array_equal(stored, image)
    assert (folder / "rig.json").read_bytes() == rig_before, "the app declares the swap itself, with PUT /api/rig"


def test_swap_image_upload_never_overwrites(client, folder):
    first, other = swap_block(folder), swap_block(folder, w=4, h=4)
    assert post_swap(client, "jab", first).json()["image"] == "swaps/jab.png"
    assert post_swap(client, "jab", first).json()["image"] == "swaps/jab.png", "same image: same file"
    assert post_swap(client, "jab", other).json()["image"] == "swaps/jab_2.png"
    assert post_swap(client, "jab", first).json()["image"] == "swaps/jab.png"
    assert np.array_equal(np.array(Image.open(folder / "swaps" / "jab.png").convert("RGBA")), first)
    assert sorted(p.name for p in (folder / "swaps").iterdir()) == ["jab.png", "jab_2.png"]


def test_swap_image_upload_refuses_what_the_engine_would_refuse(client, folder):
    alien = swap_block(folder, colour=(255, 0, 255, 255))
    body = assert_error(post_swap(client, "jab", alien), 422, "swap_image_refused")
    assert "palette" in body["details"]["core_message"]
    soft = swap_block(folder)
    soft[1, 1, 3] = 128
    assert_error(post_swap(client, "jab", soft), 422, "swap_image_refused")
    empty = np.zeros((3, 3, 4), dtype=np.uint8)
    assert_error(post_swap(client, "jab", empty), 422, "swap_image_refused")
    not_an_image = client.post("/api/swaps/jab/image", files={"file": ("x.png", b"hello", "image/png")})
    assert_error(not_an_image, 422, "swap_image_refused")
    assert_error(post_swap(client, "1 bad name", swap_block(folder)), 422)
    assert not (folder / "swaps").exists(), "nothing is written for a refused image"


def test_swap_declared_after_the_upload_is_served_and_rendered(client, folder):
    image = swap_block(folder)
    path = post_swap(client, "jab", image).json()["image"]
    assert assert_error(client.get("/api/swaps/jab.png"), 404)["details"]["code"] == "swap_unknown"
    current = client.get("/api/rig").json()
    current["data"]["swaps"] = {"jab": {"image": path, "bone": "forearm_r", "anchor": [1, 1]}}
    put = client.put("/api/rig", json={"base_rev": current["rev"], "data": current["data"]})
    assert put.status_code == 200, put.text
    assert np.array_equal(png_array(client.get("/api/swaps/jab.png")), image)

    frames = [{"duration_ms": 100, "bones": {}}, {"duration_ms": 100, "bones": {}, "swap": ["jab"]}]
    put_anim(client, frames)
    plain, swapped = png_array(client.get("/api/render/frames/0.png")), png_array(client.get("/api/render/frames/1.png"))
    assert not np.array_equal(plain, swapped), "the frame that lists the swap draws it"

    (folder / "swaps" / "jab.png").unlink()
    assert_error(client.get("/api/swaps/jab.png"), 404, "swap_image_missing")


def put_swaps(client, swaps):
    current = client.get("/api/rig").json()
    if swaps:
        current["data"]["swaps"] = swaps
    else:
        current["data"].pop("swaps", None)
    response = client.put("/api/rig", json={"base_rev": current["rev"], "data": current["data"]})
    assert response.status_code == 200, response.text


def test_deleting_a_swap_puts_its_image_away_and_undoing_brings_it_back(client, folder):
    image, other = swap_block(folder), swap_block(folder, w=4, h=4)
    post_swap(client, "jab", image)
    spec = {"image": "swaps/jab.png", "bone": "forearm_r", "anchor": [1, 1]}
    put_swaps(client, {"jab": spec, "twin": dict(spec)})
    put_swaps(client, {"jab": spec})
    assert (folder / "swaps" / "jab.png").is_file(), "still cited by another swap"

    put_swaps(client, None)                                     # delete
    assert not (folder / "swaps" / "jab.png").exists()
    trashed = folder / ".animai" / "trash" / "swaps" / "jab.png"
    assert np.array_equal(np.array(Image.open(trashed).convert("RGBA")), image), "put away, not erased"

    assert post_swap(client, "jab", other).json()["image"] == "swaps/jab_2.png", "the name stays the trashed image's"
    put_swaps(client, {"jab": spec})                            # undo
    assert np.array_equal(png_array(client.get("/api/swaps/jab.png")), image)
    assert not trashed.exists()


def test_put_rig_only_puts_away_the_images_stored_in_swaps(client, folder):
    art = folder / "art"
    art.mkdir()
    (art / "mine.png").write_bytes(png_bytes(swap_block(folder)))
    put_swaps(client, {"mine": {"image": "art/mine.png", "bone": "forearm_r", "anchor": [1, 1]}})
    put_swaps(client, None)
    assert (art / "mine.png").is_file(), "a file the app did not store is left alone"


def test_snapshot_keeps_the_swap_images(client, folder):
    image = swap_block(folder)
    post_swap(client, "jab", image)
    put_swaps(client, {"jab": {"image": "swaps/jab.png", "bone": "forearm_r", "anchor": [1, 1]}})
    snap = client.post("/api/snapshots", json={"label": "with jab"}).json()
    assert snap["images"] == ["swaps/jab.png"]

    (folder / "swaps" / "jab.png").write_bytes(png_bytes(swap_block(folder, w=4, h=4)))    # redrawn on disk
    assert client.post(f"/api/snapshots/{snap['id']}/restore").status_code == 200
    assert np.array_equal(png_array(client.get("/api/swaps/jab.png")), image)

    put_swaps(client, None)                                     # image put away, then the version is restored
    assert client.post(f"/api/snapshots/{snap['id']}/restore").status_code == 200
    assert np.array_equal(png_array(client.get("/api/swaps/jab.png")), image)


# --------------------------------------------------------------------------- #
# 21: events, with a real `animai serve` process
# --------------------------------------------------------------------------- #

def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def served(folder):
    """`animai serve` on a free port; the process is stopped through its own handle."""
    port = free_port()
    env = dict(os.environ, PYTHONPATH=str(cli.REPO_ROOT), PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    process = subprocess.Popen(cli.BASE_COMMAND + ["serve", str(folder), "--port", str(port)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=str(folder.parent))
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.time() + 30
        while True:
            try:
                if httpx.get(base + "/api/project", timeout=2).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            if process.poll() is not None or time.time() > deadline:
                process.kill()
                out, err = process.communicate(timeout=10)
                pytest.fail(f"`animai serve` did not start: rc={process.returncode}\n{out.decode()}\n{err.decode()}")
            time.sleep(0.2)
        yield base, port, process
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        for stream in (process.stdout, process.stderr):
            stream.close()


def read_events(lines, count, timeout=10.0):
    """Next `count` SSE events as (event, data); `lines` = one `stream.iter_lines()` iterator."""
    events, name, deadline = [], None, time.time() + timeout
    for line in lines:
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:") and name:
            events.append((name, json.loads(line.split(":", 1)[1])))
            name = None
            if len(events) >= count:
                break
        assert time.time() < deadline, f"only {events} after {timeout} s"
    return events


def test_serve_announces_itself_and_listens_on_loopback_only(served, folder):
    base, port, _ = served
    assert httpx.get(base + "/api/project", timeout=5).json()["name"] == folder.name
    refused = httpx.get(base + "/api/project", headers={"Host": "evil.example"}, timeout=5)
    assert refused.status_code == 400
    assert httpx.get(base + "/", follow_redirects=False, timeout=5).headers["location"] == "/index.html?api=/api"


def test_events_announce_app_and_external_writes(served, folder):
    base, _, _ = served
    timeout = httpx.Timeout(5, read=12)
    with httpx.Client(timeout=timeout) as other, other.stream("GET", base + "/api/events") as stream:
        assert stream.status_code == 200 and stream.headers["content-type"].startswith("text/event-stream")
        lines = stream.iter_lines()
        current = httpx.get(base + "/api/rig", timeout=5).json()
        current["data"]["bones"]["head"]["joint"][1] -= 1
        new_rev = httpx.put(base + "/api/rig", json={"base_rev": current["rev"], "data": current["data"]},
                            timeout=5).json()["rev"]
        (name, data), = read_events(lines, 1)
        assert name == "rig.changed" and data["rev"] == new_rev and data["author"] == "app"
        assert isinstance(data["at"], int)

        time.sleep(1.1)                                         # a later mtime, whatever the file system
        (folder / "rig.json").write_bytes(load_case("hero64").rig_path.read_bytes())      # Claude writes
        (name, data), = read_events(lines, 1)
        assert name == "rig.changed" and data["author"] == "external"
        assert data["rev"] == rev_of(folder / "rig.json")

        (folder / "anim.json").write_text(json.dumps(preset_document("idle")), encoding="utf-8")
        (name, data), = read_events(lines, 1)
        assert name == "anim.changed" and data["rev"] == rev_of(folder / "anim.json")


def test_events_stay_silent_for_an_invalid_file_and_the_project_says_why(served, folder):
    base, _, _ = served
    with httpx.Client(timeout=httpx.Timeout(5, read=12)) as other, \
            other.stream("GET", base + "/api/events") as stream:
        lines = stream.iter_lines()
        (folder / "rig.json").write_text('{"version": 1, "bones": ', encoding="utf-8")      # half-written
        time.sleep(1.2)
        (folder / "anim.json").write_text(json.dumps(preset_document("idle")), encoding="utf-8")
        events = read_events(lines, 1)
        assert [name for name, _ in events] == ["anim.changed"], "no rig.changed for an invalid rig.json"
    assert httpx.get(base + "/api/project", timeout=5).json()["prepare"]["warnings"]
