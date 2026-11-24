"""Шифрование эталонных векторов перед записью в базу данных.

Вектор лица позволяет установить личность, поэтому хранится как биометрические
персональные данные: в базе лежит только шифротекст Fernet (AES-128-CBC + HMAC-SHA256),
ключ хранится вне базы – в переменной окружения BIOMETRIC_KEY.
"""
from __future__ import annotations

import numpy as np
from cryptography.fernet import Fernet, InvalidToken


class VectorCipher:
    def __init__(self, key: str | bytes):
        if not key:
            raise ValueError('не задан ключ шифрования биометрии (BIOMETRIC_KEY)')
        self._f = Fernet(key if isinstance(key, bytes) else key.encode())

    @staticmethod
    def generate_key() -> str:
        return Fernet.generate_key().decode()

    def encrypt(self, vector: np.ndarray) -> bytes:
        data = np.asarray(vector, dtype=np.float32).tobytes()
        return self._f.encrypt(data)

    def decrypt(self, token: bytes) -> np.ndarray:
        try:
            data = self._f.decrypt(bytes(token))
        except InvalidToken as exc:
            raise ValueError('эталон поврежден или зашифрован другим ключом') from exc
        return np.frombuffer(data, dtype=np.float32).copy()
