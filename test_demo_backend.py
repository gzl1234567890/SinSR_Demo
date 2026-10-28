"""CPU-only API checks. Injected runners are test fixtures, never demo results."""
import io
import json
import logging
import os
import re
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from demo_backend import EXAMPLES, create_app


def image_bytes(size=(64, 48), color=(30, 100, 170)):
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


class DemoAPITests(unittest.TestCase):
    def setUp(self):
        temporary_parent = Path(__file__).resolve().parent / "demo_outputs"
        temporary_parent.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="api-test-", dir=temporary_parent)
        self.root = Path(self.temporary.name)
        source = self.root / "testdata" / "RealSet65"
        source.mkdir(parents=True)
        for _, _, _, filename in EXAMPLES:
            Image.new("RGB", (64, 48), (30, 100, 170)).save(source / filename)
        public_library = []
        for dataset, filename, size in [("RealSR", "Canon_001_LR4.png", (96, 64)),
                                        ("RealSet128", "scene.png", (128, 128))]:
            path = self.root / "testdata" / dataset / filename
            path.parent.mkdir(exist_ok=True)
            Image.new("RGB", size, (50, 70, 90)).save(path)
            public_library.append(dict(path=f"{dataset}/{filename}", dataset=dataset,
                                       width=size[0], height=size[1]))
        (self.root / "testdata" / "catalog.json").write_text(json.dumps({"images": public_library}), encoding="utf-8")
        static = self.root / "demo_static"
        static.mkdir()
        (static / "index.html").write_text(
            '<!doctype html><title>SinSR test</title><link rel="stylesheet" href="/static/style.css?v=__ASSET_VERSION__">'
            '<script src="/static/app.js?v=__ASSET_VERSION__"></script>', encoding="utf-8")
        (static / "style.css").write_text("body{color:blue}", encoding="utf-8")
        (static / "app.js").write_text("'use strict';", encoding="utf-8")
        self.calls = []
        self.state = dict(torch_version="test fixture", cuda_available=True, device="fake test runner",
                          weights_ready=True, missing_weights=[], live_ready=True, message="test only")

        def fake_runner(input_path, output_path, seed, progress):
            self.calls.append(seed)
            progress("test runner")
            with Image.open(input_path) as image:
                image.resize((image.width * 4, image.height * 4), Image.Resampling.NEAREST).save(output_path)
            return 0.125

        self.app = create_app(self.root, live_runner=fake_runner, environment_checker=lambda: dict(self.state))
        self.context = TestClient(self.app)
        self.client = self.context.__enter__()

    def tearDown(self):
        self.app.state.demo.executor.shutdown(wait=True, cancel_futures=True)
        self.context.__exit__(None, None, None)
        self.temporary.cleanup()

    def run_job(self, input_id="ex-dog", mode="bicubic", seed=12345):
        response = self.client.post("/api/jobs", json=dict(input_id=input_id, mode=mode, seed=seed))
        self.assertEqual(response.status_code, 200, response.text)
        identifier = response.json()["job_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = self.client.get(f"/api/jobs/{identifier}").json()
            if job["status"] in {"done", "error"}:
                return job
            time.sleep(0.01)
        self.fail("test job did not complete")

    def test_home_examples_status_and_original_images(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        items = self.client.get("/api/examples").json()
        self.assertEqual(len(items), 4)
        self.assertFalse(any(item["cached"] for item in items))
        response = self.client.get(items[0]["input_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (64, 48))
        self.assertEqual(self.client.get("/api/status").json()["cached_examples"], 0)

    def test_updated_frontend_never_reuses_an_old_bundle_version(self):
        def versioned_page():
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertNotIn("__ASSET_VERSION__", response.text)
            urls = re.findall(r'/static/(?:app\.js|style\.css)\?v=[0-9a-f]{16}', response.text)
            self.assertEqual(len(urls), 2)
            self.assertEqual(urls[0].split("?v=")[1], urls[1].split("?v=")[1])
            for url in urls:
                asset = self.client.get(url)
                self.assertEqual(asset.status_code, 200)
                self.assertEqual(asset.headers["cache-control"], "no-store")
            return urls

        previous = versioned_page()
        for filename in ("app.js", "style.css", "index.html"):
            path = self.root / "demo_static" / filename
            original = path.stat()
            path.write_bytes(path.read_bytes() + b"\n ")
            # A file copied with its previous timestamp must still get new URLs.
            os.utime(path, ns=(original.st_atime_ns, original.st_mtime_ns))
            current = versioned_page()
            self.assertNotEqual(current, previous)
            previous = current

    def test_baseline_is_explicitly_not_sinsr_and_never_replay_cache(self):
        job = self.run_job()
        self.assertEqual(job["status"], "done")
        result = job["result"]
        self.assertEqual(result["mode"], "bicubic")
        self.assertEqual(result["model"], "Bicubic")
        self.assertFalse(result["cached"])
        self.assertEqual(self.calls, [])
        self.assertEqual(list((self.root / "demo_outputs" / "cache").glob("*.json")), [])
        response = self.client.get(result["output_url"])
        self.assertEqual(Image.open(io.BytesIO(response.content)).size, (256, 192))
        download = self.client.get(result["download_url"])
        self.assertIn("attachment", download.headers["content-disposition"])
        self.assertEqual(download.headers["content-type"], "image/png")

    def test_live_saved_result_replay_retains_seed_dimensions_and_elapsed(self):
        live = self.run_job(mode="live")
        self.assertEqual(live["status"], "done")
        self.assertEqual(self.calls, [12345])
        replay = self.run_job(mode="replay")
        self.assertEqual(replay["status"], "done")
        result = replay["result"]
        self.assertEqual(result["mode"], "replay")
        self.assertEqual(result["model"], "SinSR")
        self.assertTrue(result["cached"])
        self.assertEqual(result["elapsed_seconds"], 0.125)
        self.assertEqual((result["input_width"], result["output_width"]), (64, 256))
        self.assertEqual(result["output_url"], live["result"]["output_url"])
        self.assertEqual(self.calls, [12345])
        self.assertTrue(self.client.get("/api/examples").json()[0]["cached"])

    def test_replay_rejects_different_seed_and_changed_input(self):
        self.assertEqual(self.run_job(mode="live")["status"], "done")
        with self.assertLogs("demo_backend", level=logging.ERROR):
            changed_seed = self.run_job(mode="replay", seed=54321)
        self.assertEqual(changed_seed["status"], "error")
        upload = self.client.post("/api/upload", files={"file": ("new.png", image_bytes(color=(1, 2, 3)), "image/png")}).json()
        with self.assertLogs("demo_backend", level=logging.ERROR):
            changed_input = self.run_job(input_id=upload["id"], mode="replay")
        self.assertEqual(changed_input["status"], "error")

    def test_cpu_live_preflight_fails_before_runner_or_download(self):
        self.state.update(live_ready=False, cuda_available=False, message="CPU fixture: install GPU torch")
        with self.assertLogs("demo_backend", level=logging.ERROR):
            job = self.run_job(mode="live")
        self.assertEqual(job["status"], "error")
        self.assertIn("CPU fixture", job["message"])
        self.assertFalse(self.calls)
        self.assertFalse((self.root / "weights").exists())
        # CPU machines can still play actual previously saved SinSR results.
        self.state["live_ready"] = True
        self.run_job(mode="live")
        self.state["live_ready"] = False
        self.assertEqual(self.run_job(mode="replay")["status"], "done")

    def test_upload_limits_and_invalid_content(self):
        self.assertEqual(self.client.post("/api/upload", files={"file": ("bad.png", b"not an image")}).status_code, 400)
        self.assertEqual(self.client.post("/api/upload", files={"file": ("tiny.png", image_bytes((8, 8)))}).status_code, 400)
        self.assertEqual(self.client.post("/api/upload", files={"file": ("large.png", image_bytes((1025, 32)))}).status_code, 400)
        with patch("demo_backend.MAX_UPLOAD_BYTES", 32):
            self.assertEqual(self.client.post("/api/upload", files={"file": ("large.bin", b"x" * 33)}).status_code, 413)
        upload = self.client.post("/api/upload", files={"file": ("../../中文图片.png", image_bytes())}).json()
        self.assertTrue(upload["id"].startswith("upload-"))
        self.assertEqual((upload["width"], upload["height"]), (64, 48))
        self.assertEqual(self.client.get(upload["input_url"]).status_code, 200)

    def test_path_safety_bad_inputs_origin_and_seed(self):
        self.assertEqual(self.client.get("/api/files/no-such-file.png").status_code, 404)
        self.assertEqual(self.client.get("/api/files/..%5CREADME.md").status_code, 404)
        self.assertEqual(self.client.post("/api/jobs", json={"input_id": "../../README.md"}).status_code, 404)
        self.assertEqual(self.client.post("/api/jobs", json={"input_id": "ex-dog", "seed": -1}).status_code, 422)
        self.assertEqual(self.client.post("/api/jobs", json={"input_id": "ex-dog", "mode": "unknown"}).status_code, 422)
        self.assertEqual(self.client.post("/api/jobs", headers={"Origin": "https://elsewhere.example"}, json={"input_id": "ex-dog"}).status_code, 403)
        self.assertEqual(self.client.post("/api/jobs", headers={"Origin": "http://testserver"}, json={"input_id": "ex-dog", "mode": "bicubic"}).status_code, 200)
        self.assertEqual(self.client.get("/api/jobs/no-such-job").status_code, 404)

    def test_persistent_cache_and_missing_output_rejected(self):
        live = self.run_job(mode="live")
        restarted = create_app(self.root, environment_checker=lambda: dict(self.state))
        try:
            self.assertTrue(restarted.state.demo.examples()[0]["cached"])
        finally:
            restarted.state.demo.executor.shutdown(wait=True)
        output_id = live["result"]["output_url"].split("/")[-1]
        (self.root / "demo_outputs" / "results" / output_id).unlink()
        self.assertFalse(self.client.get("/api/examples").json()[0]["cached"])
        with self.assertLogs("demo_backend", level=logging.ERROR):
            self.assertEqual(self.run_job(mode="replay")["status"], "error")

    def test_modified_saved_output_cannot_be_replayed_as_authentic(self):
        live = self.run_job(mode="live")
        output_id = live["result"]["output_url"].split("/")[-1]
        output_path = self.root / "demo_outputs" / "results" / output_id
        # An image with the correct dimensions still cannot replace a saved
        # model result: cache integrity is checked against the recorded bytes.
        Image.new("RGB", (256, 192), (255, 255, 255)).save(output_path)
        self.assertFalse(self.client.get("/api/examples").json()[0]["cached"])
        with self.assertLogs("demo_backend", level=logging.ERROR):
            self.assertEqual(self.run_job(mode="replay")["status"], "error")

    def test_library_pagination_filter_and_filename_search(self):
        first = self.client.get("/api/library?page_size=1").json()
        self.assertEqual((first["total"], first["pages"], len(first["items"])), (2, 2, 1))
        second = self.client.get("/api/library?page_size=1&page=2").json()
        self.assertNotEqual(first["items"][0]["id"], second["items"][0]["id"])
        filtered = self.client.get("/api/library?dataset=RealSR&q=canon").json()
        self.assertEqual(filtered["total"], 1)
        self.assertEqual(filtered["items"][0]["title"], "Canon_001_LR4.png")
        self.assertEqual(self.client.get("/api/library?q=absent").json()["items"], [])
        self.assertEqual(self.client.get("/api/library?dataset=unknown").status_code, 400)
        self.assertEqual(self.client.get("/api/library?page=-1").status_code, 422)

    def test_library_images_thumbnails_and_processing_use_local_assets(self):
        item = self.client.get("/api/library?dataset=RealSR").json()["items"][0]
        image = self.client.get(item["input_url"])
        self.assertEqual(Image.open(io.BytesIO(image.content)).size, (96, 64))
        thumb = self.client.get(item["thumbnail_url"])
        self.assertEqual(thumb.headers["content-type"], "image/jpeg")
        self.assertLessEqual(max(Image.open(io.BytesIO(thumb.content)).size), 192)
        self.assertEqual(self.run_job(input_id=item["id"], mode="live")["status"], "done")
        self.assertTrue(self.client.get("/api/library?dataset=RealSR").json()["items"][0]["cached"])
        self.assertEqual(self.run_job(input_id=item["id"], mode="replay")["status"], "done")
        self.assertEqual(self.client.get("/api/library/lib-invalid/image").status_code, 404)

    def test_library_manifest_cannot_serve_paths_outside_testdata(self):
        bad = {"images": [{"path": "../README.md", "dataset": "RealSR"}]}
        (self.root / "testdata" / "catalog.json").write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "testdata"):
            create_app(self.root)


if __name__ == "__main__":
    unittest.main()
