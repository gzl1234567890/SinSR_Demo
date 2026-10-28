"""Local, honest SinSR presentation API. Model imports are deferred until needed."""
from __future__ import annotations

import gc
import hashlib
import io
import json
import logging
import math
import re
import threading
import time
import uuid
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Callable, Literal
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
CACHE_VERSION = "sinsr-v1-x4-patch128-2026-10"
DEMO_CHOP_SIZE = 128
DEMO_CHOP_STRIDE = 112
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_SIDE = 1024
MAX_PIXELS = 1024 * 1024
DATASETS = ("RealSet65", "RealSR", "RealSet128")
EXAMPLES = (
    ("ex-dog", "毛发与轮廓", "观察小狗的毛发、眼睛与边缘细节。", "dog2.png"),
    ("ex-bears", "自然纹理", "比较小熊的毛发与背景纹理。", "bears.jpg"),
    ("ex-oldphoto", "老照片", "观察人物轮廓与旧照片中的细节。", "oldphoto6.png"),
    ("ex-bridge", "建筑线条", "比较桥梁边缘与规则结构。", "bridge1.jpeg"),
)
WEIGHTS = {
    "SinSR_v1.pth": "https://github.com/wyf0912/SinSR/releases/download/v1.0/SinSR_v1.pth",
    "autoencoder_vq_f4.pth": "https://github.com/zsyOAOA/ResShift/releases/download/v2.0/autoencoder_vq_f4.pth",
}
_ENV_LOCK = threading.Lock()
_ENV_CACHE: dict | None = None


def _runtime_environment() -> dict:
    """The relatively slow torch import happens in an API worker, never at startup."""
    global _ENV_CACHE
    with _ENV_LOCK:
        if _ENV_CACHE is not None:
            return dict(_ENV_CACHE)
        state = dict(torch_version="未安装", cuda_available=False, device="CPU", live_ready=False)
        try:
            import torch

            state["torch_version"] = torch.__version__
            if not torch.cuda.is_available():
                state["message"] = "当前 PyTorch 不能使用 GPU。请按演示指南安装 CUDA 12.8 版 PyTorch；现在可以查看插值对照或已保存的 SinSR 结果。"
            elif torch.cuda.device_count() != 1:
                state["message"] = "请使用 CUDA_VISIBLE_DEVICES 只选择一块显卡，再重新启动演示。"
            else:
                state.update(cuda_available=True, device=torch.cuda.get_device_name(0))
                major, minor = torch.cuda.get_device_capability(0)
                architecture = major * 10 + minor
                built_arches = [int(a.split("_")[1]) for a in torch.cuda.get_arch_list() if a.startswith("sm_")]
                if architecture >= 120 and architecture not in built_arches:
                    state["message"] = "检测到 RTX 50 系列显卡，但 PyTorch 缺少 sm_120 支持。请安装演示指南中的 PyTorch CUDA 12.8 版本。"
                else:
                    state.update(live_ready=True, message="GPU 已就绪。首次使用需要准备模型；上台前请先执行 --prepare。")
        except Exception as exc:
            state["message"] = f"运行环境尚未就绪：{type(exc).__name__}。请在 SinSR 环境中运行，并按演示指南完成依赖安装。"
        _ENV_CACHE = state
        return dict(state)


def check_environment(root: Path = ROOT) -> dict:
    state = _runtime_environment()
    missing = [name for name in WEIGHTS if not _weight_ready(root / "weights" / name)]
    state.update(weights_ready=not missing, missing_weights=missing)
    if state["live_ready"] and not missing:
        state["message"] = "GPU 与模型文件已就绪。首次推理仍需加载模型，上台前请完成预热。"
    return state


def _weight_ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 1024 * 1024


def ensure_weights(root: Path, progress: Callable[[str], None]) -> None:
    import requests

    directory = root / "weights"
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in WEIGHTS.items():
        destination = directory / name
        if _weight_ready(destination):
            continue
        partial = destination.with_suffix(".pth.part")
        progress(f"正在下载 {name}，请保持联网；上台前只需准备一次。")
        try:
            with requests.get(url, stream=True, timeout=(15, 60)) as response:
                response.raise_for_status()
                expected = int(response.headers.get("content-length", 0))
                received = 0
                next_update = 8 * 1024 * 1024
                with partial.open("wb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if chunk:
                            output.write(chunk)
                            received += len(chunk)
                            if received >= next_update:
                                total = f" / {expected / 1048576:.0f} MB" if expected else " MB"
                                progress(f"下载 {name}：{received / 1048576:.0f}{total}")
                                next_update += 8 * 1024 * 1024
            if received < 1024 * 1024 or (expected and expected != received):
                raise ValueError("下载文件不完整")
            partial.replace(destination)
        except Exception as exc:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"模型下载未完成：{name}。请在联网时执行 python app.py --prepare，或从演示指南中的官方地址手动下载。") from exc


class LiveRunner:
    """Keep exactly one sampler in GPU memory and reset its seed per request."""

    def __init__(self, root: Path):
        self.root = root
        self.sampler = None

    def __call__(self, input_path: Path, output_path: Path, seed: int, progress: Callable[[str], None]) -> float:
        state = check_environment(self.root)
        if not state["live_ready"]:
            raise RuntimeError(state["message"])
        ensure_weights(self.root, progress)
        import torch

        try:
            if self.sampler is None:
                # Leave room for the display and browser. On Windows, an
                # oversized CUDA cache can spill into slow shared system RAM.
                torch.cuda.set_per_process_memory_fraction(0.65)
                progress("正在加载 SinSR 与图像解码器；本次会完成预热。")
                from omegaconf import OmegaConf
                from upstream_compat import install_upstream_compat
                upstream = install_upstream_compat()
                from sampler import Sampler

                config = OmegaConf.load(upstream / "configs" / "SinSR.yaml")
                config.model.ckpt_path = str(self.root / "weights" / "SinSR_v1.pth")
                config.autoencoder.ckpt_path = str(self.root / "weights" / "autoencoder_vq_f4.pth")
                config.diffusion.params.timestep_respacing = 15
                self.sampler = Sampler(config, chop_size=DEMO_CHOP_SIZE, chop_stride=DEMO_CHOP_STRIDE, chop_bs=1, use_fp16=True, seed=seed)
            self.sampler.setup_seed(seed)
            self.sampler.seed = seed
            torch.cuda.empty_cache()
            progress("正在进行单步超分辨率推理。")
            # Run on in-memory tensors: Unicode project paths are safe and timing
            # measures GPU inference rather than file reads, downloads or PNG encoding.
            import numpy as np
            import torch.nn.functional as functional

            with Image.open(input_path) as source:
                rgb = np.asarray(source.convert("RGB"), dtype=np.float32) / 255.0
            height, width = rgb.shape[:2]
            tensor = torch.from_numpy(rgb.copy()).permute(2, 0, 1).unsqueeze(0).cuda()
            # The upstream sampler reflects to multiples of 64. Very small
            # uploads need replicate padding first to make reflection legal.
            tensor = functional.pad(tensor, (0, max(0, 64-width), 0, max(0, 64-height)), mode="replicate")
            torch.cuda.synchronize()
            started = time.perf_counter()
            with torch.inference_mode():
                # Reuse the upstream splitting/blending implementation, including
                # its normalization, rather than duplicating model math here.
                from utils.util_image import ImageSpliterTh

                if tensor.shape[2] > DEMO_CHOP_SIZE or tensor.shape[3] > DEMO_CHOP_SIZE:
                    splitter = ImageSpliterTh(tensor, DEMO_CHOP_SIZE, stride=DEMO_CHOP_STRIDE, sf=4, extra_bs=1)
                    for patch, indices in splitter:
                        predicted = self.sampler.sample_func((patch - 0.5) / 0.5, one_step=True)
                        splitter.update(predicted.detach(), indices)
                    prediction = splitter.gather()
                else:
                    prediction = self.sampler.sample_func((tensor - 0.5) / 0.5, one_step=True)
                prediction = (prediction[:, :, :height*4, :width*4] * 0.5 + 0.5).clamp(0, 1)
            torch.cuda.synchronize()
            elapsed = time.perf_counter() - started
            pixels = prediction[0].float().cpu().permute(1, 2, 0).numpy()
            Image.fromarray(np.round(pixels * 255).astype(np.uint8)).save(output_path)
            return elapsed
        except torch.cuda.OutOfMemoryError as exc:
            self.sampler = None
            gc.collect()
            torch.cuda.empty_cache()
            raise RuntimeError("显存不足。请关闭其他 GPU 应用，并换一张长边不超过 512 像素的图片后重试。") from exc


def _open_image(path_or_buffer) -> Image.Image:
    try:
        with Image.open(path_or_buffer) as source:
            if source.format not in {"PNG", "JPEG", "WEBP", "BMP"}:
                raise ValueError("请使用 PNG、JPG、WebP 或 BMP 图片。")
            if min(source.size) < 16 or max(source.size) > MAX_SIDE or source.width * source.height > MAX_PIXELS:
                raise ValueError("图片尺寸需至少 16×16，长边不超过 1024 像素。现场演示推荐长边不超过 512 像素。")
            source.load()
            return ImageOps.exif_transpose(source).convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise ValueError("无法读取这张图片。请重新上传有效的 PNG、JPG、WebP 或 BMP 文件。") from exc


def _digest(image: Image.Image) -> str:
    hasher = hashlib.sha256(f"{image.width}x{image.height}:".encode())
    hasher.update(image.tobytes())
    return hasher.hexdigest()


def _file_digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


@lru_cache(maxsize=256)
def _thumbnail(path: str, modified_ns: int) -> bytes:
    """Keep thumbnails in memory; do not leave generated files in the source tree."""
    image = _open_image(Path(path))
    image.thumbnail((192, 144), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=82, optimize=True)
    return output.getvalue()


class JobRequest(BaseModel):
    input_id: str = Field(min_length=1, max_length=80)
    mode: Literal["live", "replay", "bicubic"] = "live"
    seed: int = Field(default=12345, ge=0, le=2**32-1)


class DemoService:
    def __init__(self, root: Path, live_runner=None, environment_checker=None):
        self.root = root.resolve()
        self.directory = self.root / "demo_outputs"
        self.inputs = self.directory / "inputs"
        self.results = self.directory / "results"
        self.cache = self.directory / "cache"
        for folder in (self.inputs, self.results, self.cache):
            folder.mkdir(parents=True, exist_ok=True)
        self.library = self._load_library()
        self.runner = live_runner or LiveRunner(self.root)
        self.environment_checker = environment_checker or (lambda: check_environment(self.root))
        self.jobs: dict[str, dict] = {}
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sinsr-demo")

    def _load_library(self) -> dict:
        manifest = self.root / "testdata" / "catalog.json"
        if not manifest.is_file():
            return {}
        index = {}
        directory = (self.root / "testdata").resolve()
        for entry in json.loads(manifest.read_text(encoding="utf-8"))["images"]:
            relative = Path(entry["path"])
            path = (directory / relative).resolve()
            if (relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(directory)
                    or entry["dataset"] not in DATASETS or relative.parts[0] != entry["dataset"]
                    or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
                    or not path.is_file() or path.is_symlink()):
                raise ValueError("图库文件必须位于 Demo 的 testdata 目录内。")
            identifier = "lib-" + hashlib.sha256(relative.as_posix().encode()).hexdigest()[:20]
            index[identifier] = {**entry, "id": identifier, "_path": path}
        return index

    def library_page(self, dataset="all", query="", page=1, page_size=18) -> dict:
        if dataset != "all" and dataset not in DATASETS:
            raise HTTPException(400, "测试集不存在。")
        needle = query.strip().casefold()
        selected = [entry for entry in self.library.values()
                    if (dataset == "all" or entry["dataset"] == dataset)
                    and (not needle or needle in entry["path"].casefold())]
        pages = max(1, math.ceil(len(selected) / page_size))
        page = min(page, pages)
        items = []
        for entry in selected[(page - 1) * page_size:page * page_size]:
            identifier = entry["id"]
            image = _open_image(entry["_path"])
            items.append(dict(id=identifier, title=Path(entry["path"]).name,
                              dataset=entry["dataset"], width=image.width, height=image.height,
                              input_url=f"/api/library/{identifier}/image",
                              thumbnail_url=f"/api/library/{identifier}/thumbnail",
                              cached=self.cached(image, 12345) is not None))
        counts = {name: sum(entry["dataset"] == name for entry in self.library.values()) for name in DATASETS}
        return dict(items=items, total=len(selected), page=page, page_size=page_size,
                    pages=pages, datasets=counts, library_total=len(self.library))

    def source(self, input_id: str) -> Path:
        if input_id in self.library:
            return self.library[input_id]["_path"]
        for example_id, _, _, filename in EXAMPLES:
            if input_id == example_id:
                path = self.root / "testdata" / "RealSet65" / filename
                if path.is_file():
                    return path
        if re.fullmatch(r"upload-[0-9a-f]{32}", input_id):
            path = self.inputs / f"{input_id}.png"
            if path.is_file():
                return path
        raise HTTPException(404, "未找到输入图片，请重新选择示例或上传图片。")

    def file(self, file_id: str) -> Path:
        if not re.fullmatch(r"(?:upload-[0-9a-f]{32}|[0-9a-f]{32}-(?:input|sr|bicubic))\.png", file_id):
            raise HTTPException(404, "文件不存在。")
        folder = self.inputs if file_id.startswith("upload-") else self.results
        path = folder / file_id
        if not path.is_file() or path.is_symlink():
            raise HTTPException(404, "文件不存在。")
        return path

    @staticmethod
    def key(digest: str, seed: int) -> str:
        return hashlib.sha256(f"{CACHE_VERSION}:{digest}:{seed}".encode()).hexdigest()

    def cached(self, image: Image.Image, seed: int) -> dict | None:
        key = self.key(_digest(image), seed)
        manifest = self.cache / f"{key}.json"
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data["version"] != CACHE_VERSION or data["digest"] != _digest(image) or data["seed"] != seed:
                return None
            if (data["input_width"], data["input_height"]) != image.size:
                return None
            if not math.isfinite(data["elapsed_seconds"]) or data["elapsed_seconds"] < 0:
                return None
            for field in ("input_file", "baseline_file", "output_file"):
                if _file_digest(self.file(data[field])) != data["file_hashes"][field]:
                    return None
            return data
        except (OSError, ValueError, KeyError, TypeError, HTTPException):
            return None

    @staticmethod
    def result(data: dict, mode: str) -> dict:
        return dict(
            input_url=f"/api/files/{data['input_file']}",
            baseline_url=f"/api/files/{data['baseline_file']}",
            output_url=f"/api/files/{data['output_file']}",
            download_url=f"/api/download/{data['output_file']}",
            input_width=data["input_width"], input_height=data["input_height"],
            output_width=data["input_width"] * 4, output_height=data["input_height"] * 4,
            elapsed_seconds=data["elapsed_seconds"], mode=mode, seed=data["seed"],
            model="Bicubic" if mode == "bicubic" else "SinSR", cached=mode == "replay",
        )

    def examples(self) -> list[dict]:
        items = []
        for example_id, title, description, filename in EXAMPLES:
            path = self.root / "testdata" / "RealSet65" / filename
            if not path.is_file():
                continue
            image = _open_image(path)
            items.append(dict(id=example_id, title=title, description=description,
                              width=image.width, height=image.height,
                              input_url=f"/api/examples/{example_id}/image", cached=self.cached(image, 12345) is not None))
        return items

    def upload(self, content: bytes, filename: str | None) -> dict:
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "图片文件超过 20 MB，请压缩后重试。")
        try:
            image = _open_image(io.BytesIO(content))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        input_id = f"upload-{uuid.uuid4().hex}"
        image.save(self.inputs / f"{input_id}.png")
        title = Path((filename or "上传图片").replace("\\", "/")).stem[:60]
        return dict(id=input_id, width=image.width, height=image.height, title=title,
                    input_url=f"/api/files/{input_id}.png")

    def submit(self, request: JobRequest) -> str:
        source = self.source(request.input_id)
        # Pin the input when a job is submitted; uploaded or example files cannot
        # silently change underneath a queued request or a saved result.
        image = _open_image(source)
        with self.lock:
            if sum(job["status"] in {"queued", "running"} for job in self.jobs.values()) >= 4:
                raise HTTPException(429, "演示任务较多，请等待当前任务结束后重试。")
            finished = [key for key, job in self.jobs.items() if job["status"] in {"done", "error"}]
            while len(self.jobs) >= 64 and finished:
                self.jobs.pop(finished.pop(0), None)
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = dict(id=job_id, status="queued", stage="queued", message="任务已排队。")
        self.executor.submit(self._run, job_id, image, request)
        return job_id

    def _update(self, job_id: str, **changes):
        with self.lock:
            self.jobs[job_id].update(changes)

    def _run(self, job_id: str, image: Image.Image, request: JobRequest):
        self._update(job_id, status="running", stage="preparing", message="正在准备图片与对照。")
        try:
            if request.mode == "replay":
                data = self.cached(image, request.seed)
                if data is None:
                    raise RuntimeError("这张图片与当前随机种子还没有保存的 SinSR 结果。请先使用实时推理，或上台前执行 python app.py --prepare。")
                result = self.result(data, "replay")
            else:
                if request.mode == "live":
                    state = self.environment_checker()
                    if not state["live_ready"]:
                        raise RuntimeError(state["message"])
                prefix = uuid.uuid4().hex
                input_file, baseline_file, output_file = (f"{prefix}-{kind}.png" for kind in ("input", "bicubic", "sr"))
                image.save(self.results / input_file)
                started = time.perf_counter()
                baseline = image.resize((image.width * 4, image.height * 4), Image.Resampling.BICUBIC)
                baseline.save(self.results / baseline_file)
                elapsed = time.perf_counter() - started
                if request.mode == "live":
                    def progress(message: str):
                        self._update(job_id, stage="inference", message=message)
                    elapsed = self.runner(self.results / input_file, self.results / output_file, request.seed, progress)
                    with Image.open(self.results / output_file) as output:
                        if output.size != (image.width * 4, image.height * 4):
                            raise RuntimeError("推理输出尺寸异常，请重新准备模型后重试。")
                else:
                    output_file = baseline_file
                data = dict(version=CACHE_VERSION, digest=_digest(image), seed=request.seed,
                            input_file=input_file, baseline_file=baseline_file, output_file=output_file,
                            input_width=image.width, input_height=image.height, elapsed_seconds=round(elapsed, 4))
                if request.mode == "live":
                    data["file_hashes"] = {
                        field: _file_digest(self.results / data[field])
                        for field in ("input_file", "baseline_file", "output_file")
                    }
                    key = self.key(data["digest"], request.seed)
                    pending = self.cache / f"{key}.json.tmp"
                    pending.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                    pending.replace(self.cache / f"{key}.json")
                result = self.result(data, request.mode)
            self._update(job_id, status="done", stage="done", message="处理完成。", result=result)
        except Exception as exc:
            logging.getLogger(__name__).exception("Demo job %s failed", job_id)
            message = str(exc) if isinstance(exc, (RuntimeError, ValueError)) else f"处理失败（{type(exc).__name__}）。请查看启动窗口的错误详情，检查环境与模型后重试。"
            self._update(job_id, status="error", stage="error", message=message)


def frontend_version(root: Path = ROOT) -> str:
    """Keep the HTML, stylesheet and script on the same browser cache version."""
    digest = hashlib.sha256()
    for filename in ("index.html", "style.css", "app.js"):
        digest.update(filename.encode())
        digest.update((Path(root) / "demo_static" / filename).read_bytes())
    return digest.hexdigest()[:16]


def create_app(root: Path = ROOT, *, live_runner=None, environment_checker=None) -> FastAPI:
    service = DemoService(Path(root), live_runner=live_runner, environment_checker=environment_checker)

    @asynccontextmanager
    async def lifespan(_app):
        yield
        service.executor.shutdown(wait=False, cancel_futures=True)

    app = FastAPI(title="SinSR 课堂演示", docs_url=None, redoc_url=None, lifespan=lifespan)
    app.state.demo = service

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "请从当前演示页面提交任务。"}, status_code=403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse({"detail": "请从当前演示页面提交任务。"}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    static = service.root / "demo_static"
    if static.is_dir():
        app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def home():
        path = static / "index.html"
        try:
            document = path.read_text(encoding="utf-8-sig")
            version = frontend_version(service.root)
        except OSError:
            raise HTTPException(503, "演示页面尚未安装完整。")
        return HTMLResponse(document.replace("__ASSET_VERSION__", version))

    @app.get("/api/status")
    def status():
        state = dict(service.environment_checker())
        state["cached_examples"] = sum(item["cached"] for item in service.examples())
        return state

    @app.get("/api/examples")
    def examples():
        return service.examples()

    @app.get("/api/library")
    def library(dataset: str = "all", q: str = Query(default="", max_length=120),
                page: int = Query(default=1, ge=1), page_size: int = Query(default=18, ge=1, le=60)):
        return service.library_page(dataset, q, page, page_size)

    @app.get("/api/library/{input_id}/image")
    def library_image(input_id: str):
        if input_id not in service.library:
            raise HTTPException(404, "图库图片不存在。")
        return FileResponse(service.source(input_id))

    @app.get("/api/library/{input_id}/thumbnail")
    def library_thumbnail(input_id: str):
        if input_id not in service.library:
            raise HTTPException(404, "图库图片不存在。")
        path = service.source(input_id)
        data = _thumbnail(str(path), path.stat().st_mtime_ns)
        return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/api/examples/{input_id}/image")
    def example_image(input_id: str):
        if not input_id.startswith("ex-"):
            raise HTTPException(404, "示例不存在。")
        return FileResponse(service.source(input_id))

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        try:
            # Read at most the limit plus one byte, even if the peer streams a
            # request without Content-Length. Decode only after the size check.
            content = await file.read(MAX_UPLOAD_BYTES + 1)
            return service.upload(content, file.filename)
        finally:
            await file.close()

    @app.post("/api/jobs")
    def submit(body: JobRequest):
        return {"job_id": service.submit(body)}

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str):
        with service.lock:
            if job_id not in service.jobs:
                raise HTTPException(404, "任务不存在或已经过期，请重新开始。")
            return dict(service.jobs[job_id])

    @app.get("/api/files/{file_id}")
    def generated_file(file_id: str):
        return FileResponse(service.file(file_id), media_type="image/png")

    @app.get("/api/download/{file_id}")
    def download(file_id: str):
        return FileResponse(service.file(file_id), filename=f"SinSR-{file_id}", media_type="image/png")

    return app


def prepare_demo(progress=print, root: Path = ROOT):
    """Download, warm up and save *real* fixed-seed SinSR results for all examples."""
    root = Path(root)
    state = check_environment(root)
    if not state["live_ready"]:
        raise RuntimeError(state["message"])
    import torch
    torch.cuda.reset_peak_memory_stats()
    service = DemoService(root)
    try:
        ensure_weights(root, progress)
        examples = service.examples()
        if not examples:
            raise RuntimeError("找不到演示示例，请检查 testdata/RealSet65 文件夹。")
        # Separate warm-up from measured, reproducible example runs.
        progress("正在预热模型。首次加载可能需要几十秒，请在上台前完成。")
        warmup_source = service.source("ex-bears")
        warmup_output = service.results / f"{uuid.uuid4().hex}-sr.png"
        service.runner(warmup_source, warmup_output, 12345, progress)
        warmup_output.unlink(missing_ok=True)
        results = []
        measured_examples = []
        for index, example in enumerate(examples, 1):
            progress(f"[{index}/{len(examples)}] 正在保存真实 SinSR 结果：{example['title']}")
            job_id = uuid.uuid4().hex
            service.jobs[job_id] = dict(id=job_id, status="queued", stage="queued", message="")
            service._run(job_id, _open_image(service.source(example["id"])), JobRequest(input_id=example["id"], mode="live"))
            job = service.jobs[job_id]
            if job["status"] != "done":
                raise RuntimeError(job["message"])
            results.append(job["result"])
            measured_examples.append(dict(example_id=example["id"], title=example["title"], **job["result"]))
            progress(f"已保存，GPU 推理 {job['result']['elapsed_seconds']:.3f} 秒。")
        report = dict(environment=check_environment(root), seed=12345, scale=4, chop_size=DEMO_CHOP_SIZE,
                      max_memory_allocated_mib=round(torch.cuda.max_memory_allocated() / 1048576, 1),
                      max_memory_reserved_mib=round(torch.cuda.max_memory_reserved() / 1048576, 1),
                      examples=measured_examples)
        (service.directory / "preparation_report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        progress("准备完成。重新启动页面后，选择「已保存结果」即可离线即时展示。")
        progress(f"本机测量记录：{service.directory / 'preparation_report.json'}")
        return results
    finally:
        service.executor.shutdown(wait=False, cancel_futures=True)
