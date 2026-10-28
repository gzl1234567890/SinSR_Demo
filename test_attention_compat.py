"""Verify memory-bounded native attention preserves pretrained VQGAN math."""
import unittest
from unittest.mock import patch

import torch

from upstream_compat import install_upstream_compat, verify_vendor_sources

install_upstream_compat()
from ldm.modules.diffusionmodules.model import AttnBlock


class NativeAttentionTests(unittest.TestCase):
    def test_native_and_chunked_attention_match_global_reference(self):
        torch.manual_seed(7)
        block = AttnBlock(32).double().eval()
        image = torch.randn(2, 32, 7, 9, dtype=torch.float64)
        with torch.no_grad():
            normalized = block.norm(image)
            query = block.q(normalized).flatten(2).transpose(1, 2)
            key = block.k(normalized).flatten(2)
            value = block.v(normalized).flatten(2)
            weights = (query @ key / (32 ** 0.5)).softmax(dim=-1)
            reference = image + block.proj_out((value @ weights.transpose(1, 2)).reshape_as(image))
            direct = block(image)
            # Force several chunks and verify they still see global keys, not
            # merely the matching query slice, including the final short chunk.
            with patch("upstream_compat.ATTENTION_QUERY_CHUNK", 11):
                chunked = block(image)
        torch.testing.assert_close(direct, reference, rtol=1e-10, atol=1e-10)
        torch.testing.assert_close(chunked, reference, rtol=1e-10, atol=1e-10)

    def test_upstream_source_files_stay_pristine_after_runtime_adaptation(self):
        verified = verify_vendor_sources()
        self.assertGreater(verified["verified_files"], 50)
        self.assertFalse(verified["source_files_modified"])


if __name__ == "__main__":
    unittest.main()
