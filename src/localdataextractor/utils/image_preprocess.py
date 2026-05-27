from __future__ import annotations

from typing import TYPE_CHECKING

from localdataextractor.config import ImagePreprocessConfig

if TYPE_CHECKING:
    from PIL.Image import Image as PILImage


def _load_pil():
    from PIL import Image, ImageOps, ImageFilter  # type: ignore
    return Image, ImageOps, ImageFilter


def _load_numpy():
    import numpy as np  # type: ignore
    return np


def _try_load_cv2():
    try:
        import cv2  # type: ignore
        return cv2
    except Exception:
        return None


def _try_load_skimage_filters():
    try:
        from skimage.filters import threshold_sauvola  # type: ignore
        return threshold_sauvola
    except Exception:
        return None


def preprocess_for_ocr(
    image: "PILImage", config: ImagePreprocessConfig,
) -> tuple["PILImage", list[str]]:
    """Apply OCR-friendly preprocessing to a PIL image.

    Pipeline order: grayscale -> denoise -> deskew -> binarize ->
    margin trim -> upscale. All steps are individually opt-in via
    config. Returns the processed image and a list of notes describing
    which steps ran.
    """
    notes: list[str] = []
    if not config.enabled:
        return image, notes

    Image, ImageOps, ImageFilter = _load_pil()
    np = _load_numpy()
    cv2 = _try_load_cv2()

    img = image
    if img.mode not in {"L", "RGB", "RGBA"}:
        img = img.convert("RGB")

    if config.grayscale and img.mode != "L":
        img = ImageOps.grayscale(img)
        notes.append("grayscale")

    if config.denoise:
        if cv2 is not None and img.mode == "L":
            arr = np.array(img)
            arr = cv2.fastNlMeansDenoising(arr, h=10)
            img = Image.fromarray(arr)
            notes.append("denoise_cv2")
        else:
            img = img.filter(ImageFilter.MedianFilter(size=3))
            notes.append("denoise_median")

    if config.deskew:
        angle = _estimate_skew_angle(img, cv2, np)
        if angle is not None and abs(angle) > 0.2:
            img = img.rotate(
                -angle,
                resample=Image.BICUBIC,
                expand=True,
                fillcolor=255 if img.mode == "L" else (255, 255, 255),
            )
            notes.append(f"deskew:{angle:.2f}deg")

    if config.binarize and config.binarize_method != "none":
        method = config.binarize_method
        if img.mode != "L":
            img = ImageOps.grayscale(img)
        if method == "sauvola":
            sauvola = _try_load_skimage_filters()
            if sauvola is not None:
                arr = np.array(img)
                thresh = sauvola(arr, window_size=25)
                bin_arr = (arr > thresh).astype("uint8") * 255
                img = Image.fromarray(bin_arr, mode="L")
                notes.append("binarize_sauvola")
            elif cv2 is not None:
                arr = np.array(img)
                arr = cv2.adaptiveThreshold(
                    arr, 255,
                    cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY,
                    31, 15,
                )
                img = Image.fromarray(arr, mode="L")
                notes.append("binarize_adaptive_cv2")
            else:
                img = _otsu_pil(img, np)
                notes.append("binarize_otsu_fallback")
        elif method == "otsu":
            if cv2 is not None:
                arr = np.array(img)
                _, arr = cv2.threshold(
                    arr, 0, 255,
                    cv2.THRESH_BINARY + cv2.THRESH_OTSU,
                )
                img = Image.fromarray(arr, mode="L")
                notes.append("binarize_otsu_cv2")
            else:
                img = _otsu_pil(img, np)
                notes.append("binarize_otsu_pil")

    if config.margin_trim:
        trimmed = _trim_margins(img, np)
        if trimmed is not None:
            img = trimmed
            notes.append("margin_trim")

    if config.target_long_edge:
        w, h = img.size
        long_edge = max(w, h)
        if long_edge < config.target_long_edge:
            scale = config.target_long_edge / long_edge
            new_size = (int(w * scale), int(h * scale))
            img = img.resize(new_size, resample=Image.LANCZOS)
            notes.append(f"upscale:{scale:.2f}x")

    return img, notes


def _estimate_skew_angle(
    img: "PILImage", cv2, np,
) -> float | None:
    if cv2 is None:
        return None
    try:
        arr = np.array(
            img if img.mode == "L" else img.convert("L")
        )
        inverted = 255 - arr
        coords = np.column_stack(np.where(inverted > 128))
        if coords.shape[0] < 100:
            return None
        rect = cv2.minAreaRect(coords[:, ::-1])
        angle = rect[-1]
        if angle < -45:
            angle = 90 + angle
        if abs(angle) > 15:
            return None
        return float(angle)
    except Exception:
        return None


def _otsu_pil(img: "PILImage", np) -> "PILImage":
    from PIL import Image  # type: ignore
    arr = np.array(img)
    hist, _ = np.histogram(arr.ravel(), bins=256, range=(0, 256))
    total = arr.size
    sum_total = np.dot(np.arange(256), hist)
    sum_b = 0.0
    w_b = 0.0
    max_var = 0.0
    threshold = 127
    for i in range(256):
        w_b += hist[i]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += i * hist[i]
        m_b = sum_b / w_b
        m_f = (sum_total - sum_b) / w_f
        var_between = w_b * w_f * (m_b - m_f) ** 2
        if var_between > max_var:
            max_var = var_between
            threshold = i
    bin_arr = (arr > threshold).astype("uint8") * 255
    return Image.fromarray(bin_arr, mode="L")


def _trim_margins(img: "PILImage", np) -> "PILImage | None":
    try:
        arr = np.array(
            img if img.mode == "L" else img.convert("L")
        )
        mask = arr < 240
        if not mask.any():
            return None
        rows = np.where(mask.any(axis=1))[0]
        cols = np.where(mask.any(axis=0))[0]
        top, bottom = int(rows[0]), int(rows[-1]) + 1
        left, right = int(cols[0]), int(cols[-1]) + 1
        pad = 8
        h, w = arr.shape
        top = max(0, top - pad)
        left = max(0, left - pad)
        bottom = min(h, bottom + pad)
        right = min(w, right + pad)
        if right - left < 32 or bottom - top < 32:
            return None
        return img.crop((left, top, right, bottom))
    except Exception:
        return None
