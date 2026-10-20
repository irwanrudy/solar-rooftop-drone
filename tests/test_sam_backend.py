import warnings

import numpy as np
import pytest

import sam_backend


def test_resolve_device_auto_prefers_cuda():
    assert sam_backend.resolve_device("auto", True) == "cuda"


def test_resolve_device_falls_back_to_cpu_with_warning():
    with pytest.warns(UserWarning, match="CPU"):
        assert sam_backend.resolve_device("auto", False) == "cpu"
    with pytest.warns(UserWarning, match="CPU"):
        assert sam_backend.resolve_device("cuda", False) == "cpu"


def test_resolve_device_explicit_cpu_has_no_warning():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert sam_backend.resolve_device("cpu", True) == "cpu"


def test_ensure_checkpoint_returns_existing_file_without_download(tmp_path):
    f = tmp_path / sam_backend.CHECKPOINTS["vit_b"][0]
    f.write_bytes(b"x")
    assert sam_backend.ensure_checkpoint("vit_b", tmp_path) == f


def test_ensure_checkpoint_rejects_unknown_model(tmp_path):
    with pytest.raises(ValueError, match="vit_x"):
        sam_backend.ensure_checkpoint("vit_x", tmp_path)


@pytest.mark.slow
def test_sam_backend_smoke_on_blank_image():
    torch = pytest.importorskip("torch")
    pytest.importorskip("segment_anything")
    from pathlib import Path

    models = Path(__file__).resolve().parent.parent / "models"
    if not (models / sam_backend.CHECKPOINTS["vit_b"][0]).exists():
        pytest.skip("bobot vit_b belum diunduh")
    backend = sam_backend.SamBackend("vit_b", models, "auto", {"points_per_side": 8})
    img = np.full((256, 256, 3), 128, dtype="uint8")
    assert isinstance(backend.generate(img), list)
    masks, scores = backend.predict_box(img, [50, 50, 150, 150])
    assert masks.shape == (3, 256, 256) and scores.shape == (3,)
