"""Hash de contraseñas con scrypt de la biblioteca estándar (DOC-25).

Formato: ``scrypt$<n>$<r>$<p>$<sal base64>$<hash base64>``. No requiere
dependencias externas y funciona igual en Windows y Linux. La contraseña en
claro nunca se guarda ni se registra: solo se configura el hash por entorno.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

SCHEME = "scrypt"
N, R, P = 2**14, 8, 1
SALT_BYTES = 16
KEY_BYTES = 32
MIN_PASSWORD_CHARS = 12
MAX_PASSWORD_CHARS = 1024


class InvalidPasswordHashError(ValueError):
    """El hash configurado no tiene el formato esperado."""


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=KEY_BYTES, maxmem=64 * 1024 * 1024
    )


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_CHARS:
        raise ValueError(f"la contraseña debe tener al menos {MIN_PASSWORD_CHARS} caracteres")
    if len(password) > MAX_PASSWORD_CHARS:
        raise ValueError("la contraseña es demasiado larga")


def hash_password(password: str) -> str:
    """Devuelve el hash scrypt de ``password`` con sal aleatoria."""
    validate_new_password(password)
    salt = secrets.token_bytes(SALT_BYTES)
    return f"{SCHEME}${N}${R}${P}${_b64(salt)}${_b64(_derive(password, salt, N, R, P))}"


def parse_hash(encoded: str) -> tuple[int, int, int, bytes, bytes]:
    parts = encoded.strip().split("$")
    if len(parts) != 6 or parts[0] != SCHEME:
        raise InvalidPasswordHashError("hash no válido: genere uno con 'python -m backend.app.cli hash-password'")
    try:
        n, r, p = (int(x) for x in parts[1:4])
        salt = base64.b64decode(parts[4], validate=True)
        key = base64.b64decode(parts[5], validate=True)
    except ValueError as exc:
        raise InvalidPasswordHashError("hash no válido: componentes mal formados") from exc
    if n < 2**14 or n & (n - 1) or r < 1 or p < 1 or len(salt) < 16 or len(key) != KEY_BYTES:
        raise InvalidPasswordHashError("hash no válido: parámetros scrypt insuficientes")
    return n, r, p, salt, key


def verify_password(password: str, encoded: str) -> bool:
    """Comparación en tiempo constante; ``False`` ante cualquier entrada inválida."""
    if not password or len(password) > MAX_PASSWORD_CHARS:
        return False
    n, r, p, salt, key = parse_hash(encoded)
    return hmac.compare_digest(_derive(password, salt, n, r, p), key)
