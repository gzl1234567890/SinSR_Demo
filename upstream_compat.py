"""Demo-only compatibility layer; never rewrites upstream source files."""
from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path
import sys
import threading

UPSTREAM_DIR = Path(__file__).resolve().parent / "vendor" / "SinSR"
ATTENTION_QUERY_CHUNK = 1024
_LOCK = threading.Lock()
_INSTALLED = False


def verify_vendor_sources() -> dict:
    """Compare the bundled inference subset with its recorded Git blob hashes."""
    origin = json.loads((UPSTREAM_DIR / "ORIGIN.json").read_text(encoding="utf-8"))
    changed = []
    for relative, expected in origin["files_sha256"].items():
        path = (UPSTREAM_DIR / relative).resolve()
        if not path.is_relative_to(UPSTREAM_DIR.resolve()):
            raise ValueError("Invalid vendor manifest path")
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            changed.append(relative)
    if changed:
        raise ValueError("Bundled upstream files differ from the pinned revision: " + ", ".join(changed))
    return {"repository": origin["repository"], "commit": origin["commit"],
            "verified_files": len(origin["files_sha256"]), "source_files_modified": False}


def memory_bounded_attention(self, x):
    """Same single-head attention and projections, with global keys per query chunk."""
    import torch

    normalized = self.norm(x)
    q, k, v = self.q(normalized), self.k(normalized), self.v(normalized)
    b, c, h, w = q.shape
    q, k, v = [item.flatten(2).transpose(1, 2).unsqueeze(1).contiguous()
               for item in (q, k, v)]
    chunks = [torch.nn.functional.scaled_dot_product_attention(
        query, k, v, dropout_p=0.0, is_causal=False)
        for query in q.split(ATTENTION_QUERY_CHUNK, dim=2)]
    attended = torch.cat(chunks, dim=2).squeeze(1).transpose(1, 2).reshape(b, c, h, w)
    return x + self.proj_out(attended)


def install_upstream_compat() -> Path:
    """Activate compatibility in this demo process without editing the paper repo."""
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return UPSTREAM_DIR
        verify_vendor_sources()
        sys.dont_write_bytecode = True
        source = str(UPSTREAM_DIR)
        if source not in sys.path:
            sys.path.insert(0, source)
        # The upstream dataset import uses a torchvision module removed in 0.17.
        # Alias the supported implementation only in this Python process.
        from torchvision.transforms import functional
        sys.modules.setdefault("torchvision.transforms.functional_tensor", functional)
        model = importlib.import_module("ldm.modules.diffusionmodules.model")
        if not Path(model.__file__).resolve().is_relative_to(UPSTREAM_DIR):
            raise RuntimeError("Another SinSR engine was imported; start the demo in a fresh Python process.")
        model.AttnBlock.forward = memory_bounded_attention
        # Keep the packaged recipe independent of optional, platform-specific wheels.
        model.XFORMERS_IS_AVAILBLE = False
        importlib.import_module("ldm.modules.attention").XFORMERS_IS_AVAILBLE = False
        importlib.import_module("models.unet").XFORMERS_IS_AVAILBLE = False
        _INSTALLED = True
        return UPSTREAM_DIR
