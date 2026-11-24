"""Чтение изображений из запроса только в память (на диск кадры не попадают)."""
import base64

import cv2
import numpy as np

MAX_SIDE = 1280


def decode_bytes(data: bytes):
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError('файл не является изображением JPEG или PNG')
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        k = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * k), int(h * k)))
    return img


def decode_data_url(s: str):
    """Кадр с камеры браузера в виде data:image/jpeg;base64,..."""
    if ',' in s:
        s = s.split(',', 1)[1]
    return decode_bytes(base64.b64decode(s))


def frames_from_request(request, field='frames', limit=5):
    files = request.FILES.getlist(field)[:limit]
    return [decode_bytes(f.read()) for f in files]
