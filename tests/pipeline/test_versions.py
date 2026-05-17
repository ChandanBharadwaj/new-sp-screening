"""Version stamping tests (no DB)."""
from pathlib import Path

from app.pipeline.versions import _sha256_file, compute_static


class TestSha256File:
    def test_hashes_existing_file(self, tmp_path: Path) -> None:
        p = tmp_path / "model.txt"
        p.write_bytes(b"hello")
        h1 = _sha256_file(str(p))
        assert h1 is not None and h1.startswith("sha256:")

    def test_changes_with_content(self, tmp_path: Path) -> None:
        p = tmp_path / "model.txt"
        p.write_bytes(b"hello")
        h1 = _sha256_file(str(p))
        p.write_bytes(b"world")
        h2 = _sha256_file(str(p))
        assert h1 != h2

    def test_returns_none_for_missing(self) -> None:
        assert _sha256_file("/nonexistent/path/here.bin") is None


class TestComputeStatic:
    def test_shape(self) -> None:
        s = compute_static()
        assert "engine" in s
        assert "embedder" in s
        assert "reranker" in s
        assert "ner" in s
        assert "ltr_hash" in s  # may be None if artifact absent in test env
