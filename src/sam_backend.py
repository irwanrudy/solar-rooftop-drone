"""Pembungkus Segment Anything Model (SAM). Torch diimpor malas.

Modul ini bisa diimpor tanpa torch (untuk tes); torch baru dibutuhkan saat
`SamBackend` dibuat. Bobot diunduh ke folder `models/` pada pemakaian pertama.
"""

from __future__ import annotations

import urllib.request
import warnings
from pathlib import Path

import numpy as np

BASE_URL = "https://dl.fbaipublicfiles.com/segment_anything/"
CHECKPOINTS = {
    "vit_b": ("sam_vit_b_01ec64.pth", "375 MB"),
    "vit_l": ("sam_vit_l_0b3195.pth", "1,2 GB"),
    "vit_h": ("sam_vit_h_4b8939.pth", "2,5 GB"),
}


def resolve_device(requested: str, cuda_available: bool) -> str:
    """Pilih device. 'auto'/'cuda' tanpa CUDA jatuh ke CPU dengan peringatan."""
    if requested == "cpu":
        return "cpu"
    if requested in ("auto", "cuda"):
        if cuda_available:
            return "cuda"
        warnings.warn("CUDA tidak tersedia, memakai CPU (akan jauh lebih lambat).", UserWarning)
        return "cpu"
    raise ValueError(f"device tidak dikenal: {requested!r} (pakai auto, cuda, atau cpu)")


def ensure_checkpoint(model_type: str, directory: Path) -> Path:
    """Kembalikan path bobot; unduh jika belum ada."""
    if model_type not in CHECKPOINTS:
        raise ValueError(f"model_type {model_type!r} tidak dikenal; pilih salah satu {list(CHECKPOINTS)}")
    name, size = CHECKPOINTS[model_type]
    path = Path(directory) / name
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        print(f"Mengunduh bobot SAM {model_type} ({size}) ke {path} ...")
        urllib.request.urlretrieve(BASE_URL + name, path)
    return path


class SamBackend:
    """SAM untuk segmentasi otomatis (`generate`) dan dipandu kotak (`predict_box`)."""

    def __init__(self, model_type: str, checkpoint_dir: Path, device: str = "auto", amg: dict | None = None):
        try:
            import torch
            from segment_anything import SamAutomaticMaskGenerator, SamPredictor, sam_model_registry
        except ImportError as exc:  # pragma: no cover - bergantung lingkungan
            raise SystemExit(
                "torch/segment-anything belum terpasang. Lihat README: pip install -r requirements-sam.txt"
            ) from exc
        self.device = resolve_device(device, torch.cuda.is_available())
        checkpoint = ensure_checkpoint(model_type, Path(checkpoint_dir))
        sam = sam_model_registry[model_type](checkpoint=str(checkpoint)).to(self.device)
        self._generator = SamAutomaticMaskGenerator(sam, **(amg or {}))
        self._predictor = SamPredictor(sam)

    def generate(self, image_hwc: np.ndarray) -> list[np.ndarray]:
        """Mask boolean (H, W) hasil segmentasi otomatis pada citra RGB uint8 (H, W, 3)."""
        return [m["segmentation"] for m in self._generator.generate(image_hwc)]

    def predict_box(self, image_hwc: np.ndarray, box_xyxy) -> tuple[np.ndarray, np.ndarray]:
        """Tiga kandidat mask (3, H, W) dan skornya untuk satu kotak (x0, y0, x1, y1) piksel."""
        self._predictor.set_image(image_hwc)
        masks, scores, _ = self._predictor.predict(
            box=np.asarray(box_xyxy, dtype="float32"), multimask_output=True
        )
        return masks, scores
