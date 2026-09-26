"""Memory's model files are checked against pinned SHA-256s at load.

chromadb only verifies its MiniLM archive when downloading; an existing
extracted folder is checked for existence alone — a truncated model.onnx
(33 MB of 90) sat on the dev machine and failed as InvalidProtobuf. Now a
mismatch is repaired (re-extract / re-download) or fails loudly."""
import shutil

import pytest
from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

from backend.core.memory import embedding
from backend.core.memory.embedding import (
    EmbeddingUnavailable,
    LocalEmbeddingFunction,
    ModelIntegrityError,
)

REAL = ONNXMiniLM_L6_V2.DOWNLOAD_PATH


@pytest.fixture
def cache_copy(tmp_path, monkeypatch):
    """A private copy of the verified archive, so the real cache is never touched."""
    root = tmp_path / "all-MiniLM-L6-v2"
    root.mkdir()
    shutil.copy(REAL / ONNXMiniLM_L6_V2.ARCHIVE_FILENAME, root)
    monkeypatch.setattr(ONNXMiniLM_L6_V2, "DOWNLOAD_PATH", root)
    embedding._models.clear()
    yield root
    embedding._models.clear()


def test_a_truncated_model_is_re_extracted_and_then_works(cache_copy):
    m = ONNXMiniLM_L6_V2()
    m._download_model_if_not_exists()
    model = cache_copy / "onnx" / "model.onnx"
    good_size = model.stat().st_size
    model.write_bytes(model.read_bytes()[: good_size // 3])      # the failure seen live

    embedding._verify_minilm_l6(m)
    assert model.stat().st_size == good_size
    assert len(m(["hello"])[0]) == 384


def test_an_unrepairable_mismatch_fails_loudly(cache_copy, monkeypatch, caplog):
    monkeypatch.setitem(embedding._PINNED_FOR, "onnx/model.onnx", "0" * 64)
    with pytest.raises(ModelIntegrityError, match="SHA-256"):
        embedding._verify_minilm_l6(ONNXMiniLM_L6_V2())
    assert "still do not match" in caplog.text


def test_memory_refuses_rather_than_embedding_with_a_bad_model(cache_copy, monkeypatch):
    monkeypatch.setitem(embedding._PINNED_FOR, "onnx/model.onnx", "0" * 64)
    with pytest.raises(EmbeddingUnavailable, match="SHA-256"):
        LocalEmbeddingFunction("t", "minilm-l6")(["x"])


def test_hf_files_are_re_downloaded_once_then_fail(tmp_path, monkeypatch):
    bad = tmp_path / "bad.onnx"
    bad.write_bytes(b"not a model")
    calls = []

    def fake_download(repo, name, force_download=False, local_files_only=False):
        calls.append((name, force_download, local_files_only))
        return str(bad)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", fake_download)
    with pytest.raises(ModelIntegrityError):
        embedding._verified_hf_files()
    assert any(force for _n, force, _l in calls), "never tried a fresh download"
    assert calls[0][2] is True, "should look in the local cache first"
