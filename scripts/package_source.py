"""Build a portable submission; include only public examples and current real results."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT))

from demo_backend import EXAMPLES, DemoService, _file_digest, _open_image
from upstream_compat import verify_vendor_sources


def submission_files() -> list[Path]:
    verify_vendor_sources()
    names = ["app.py", "demo_backend.py", "upstream_compat.py", "README.md", "LICENSE",
             "THIRD_PARTY_NOTICES.md", "CHANGELOG.md", "requirements.txt", "requirements-dev.txt",
             "setup_demo.ps1", "start_demo.bat", ".gitignore", ".gitattributes",
             "PRODUCT.md", "DESIGN.md", "testdata/catalog.json",
             "test_demo_backend.py", "test_attention_compat.py", "scripts/package_source.py",
             "weights/download_manifest.json", "demo_outputs/preparation_report.json"]
    files = {ROOT / name for name in names}
    files.update(path for path in (ROOT / "demo_static").rglob("*") if path.is_file())
    origin_path = ROOT / "vendor" / "SinSR" / "ORIGIN.json"
    origin = json.loads(origin_path.read_text(encoding="utf-8"))
    files.add(origin_path)
    files.update(origin_path.parent / name for name in origin["files_sha256"])
    service = DemoService(ROOT)
    try:
        # Ship the complete public dataset catalogue, but never private uploads.
        for entry in service.library.values():
            path = entry["_path"]
            if _file_digest(path) != entry["sha256"]:
                raise ValueError(f"Bundled dataset image changed: {entry['path']}")
            files.add(path)
        # Select only the four public repository examples. Never export uploads
        # or unrelated results even if they have the same random seed.
        for example_id, _, _, filename in EXAMPLES:
            source = ROOT / "testdata" / "RealSet65" / filename
            files.add(source)
            image = _open_image(source)
            cached = service.cached(image, 12345)
            if cached is None:
                raise RuntimeError(f"Missing valid real result for {example_id}; run python app.py --prepare first.")
            files.add(service.cache / f"{service.key(cached['digest'], 12345)}.json")
            files.update(service.results / cached[field] for field in ("input_file", "baseline_file", "output_file"))
    finally:
        service.executor.shutdown(wait=False, cancel_futures=True)
    preview = ROOT / "docs" / "ui-preview.png"
    if preview.is_file():
        files.add(preview)
    for path in files:
        if not path.resolve().is_relative_to(ROOT) or not path.is_file() or path.is_symlink():
            raise ValueError(f"Invalid submission file: {path}")
        if path.suffix in {".pth", ".whl", ".pyc", ".part"} or path.name == "python_path.local.txt":
            raise ValueError(f"Runtime or temporary file cannot enter the submission: {path}")
    return sorted(files)


def main():
    files = submission_files()
    directory = ROOT / "dist"
    directory.mkdir(exist_ok=True)
    target = directory / "sinsr_demo_source.zip"
    partial = target.with_suffix(".zip.tmp")
    with zipfile.ZipFile(partial, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in files:
            archive.write(path, "sinsr_demo/" + path.relative_to(ROOT).as_posix())
    with zipfile.ZipFile(partial) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError(f"Archive validation failed: {bad}")
    partial.replace(target)
    print(f"Created: {target}")
    print(f"Files: {len(files)}; size: {target.stat().st_size / 1048576:.2f} MiB")
    print("Includes source, public examples and real replay results; excludes weights, environments and temporary files.")


if __name__ == "__main__":
    main()
