from __future__ import annotations

import os
import warnings

# Enable PyTorch MPS -> CPU fallback for ops the Apple Silicon
# backend doesn't implement (e.g. float64 used by Docling's
# RT-DETR layout model). Must be set before torch is imported.
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

# camelot-py pulls a newer chardet than requests' version-check
# accepts; the warning is cosmetic and doesn't affect behavior.
warnings.filterwarnings(
    "ignore",
    message=r".*doesn't match a supported version!.*",
)

__all__ = ["__version__"]

__version__ = "0.1.0"
