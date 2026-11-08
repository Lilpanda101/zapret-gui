"""Подписанный update-manifest.json: единственное место с доверенными ключами.

Порядок проверки (как в оригинале ``zapret_update.manifest.load_signed``):
сначала подпись Ed25519 над точными байтами - до разбора JSON, - потом
продукт, канал, ключ из манифеста и формат. Битый манифест не применяется.

Публичные ключи портированы из оригинального репозитория Zapret GUI
(``TRUSTED_KEYS``): рабочий ``gui-2026a`` и запасной ``gui-reserve-1``.
Закрытых частей здесь нет и быть не должно: они лежат на машине сборки.
"""

from __future__ import annotations

import base64
import binascii
import json
from collections.abc import Mapping

from ed25519 import verify_ed25519_signature

PRODUCT = "zapret-gui"
CHANNELS = ("dev", "stable")

# Единственное место, где живут доверенные публичные ключи апдейтера.
# Ключ в updater.py, main.py или тестах не дублировать.
TRUSTED_KEYS: dict[str, bytes] = {
    "gui-2026a": base64.b64decode("EHFnPsESeiNIq28c+jcvmqeClxDTPheSo/NgR+ea+kI="),
    "gui-reserve-1": base64.b64decode("c6fNXZOtY5he05hDoxEx9Y7Zkcej0F0MaeE9tekbn1s="),
}

MANIFEST_NAME = "update-manifest.json"
SIGNATURE_NAME = MANIFEST_NAME + ".sig"
MAX_MANIFEST_BYTES = 4 * 1024 * 1024
MAX_SIGNATURE_BYTES = 1024


class ManifestSignatureError(ValueError):
    """Манифест не прошёл проверку подписи или формата. ``code`` - причина."""

    def __init__(self, message: str, code: str = "sign") -> None:
        super().__init__(message)
        self.code = code


def decode_signature(signature: bytes | str) -> bytes:
    """Подпись лежит в файле base64-текстом; 64 байта."""
    text = signature.decode("ascii", "replace") if isinstance(signature, bytes) else str(signature)
    try:
        raw = base64.b64decode(text.strip(), validate=True)
    except (binascii.Error, ValueError):
        raw = b""
    if len(raw) != 64:
        raise ManifestSignatureError("подпись списка выпуска повреждена", "sign")
    return raw


def signing_key_id(raw: bytes, signature: bytes | str, trusted: Mapping[str, bytes] | None = None) -> str:
    """Каким из доверенных ключей подписан манифест; ошибка, если ни одним."""
    if trusted is None:
        trusted = TRUSTED_KEYS
    if len(raw) > MAX_MANIFEST_BYTES:
        raise ManifestSignatureError("список выпуска слишком велик", "format")
    if isinstance(signature, bytes) and len(signature) > MAX_SIGNATURE_BYTES:
        raise ManifestSignatureError("подпись списка выпуска повреждена", "sign")
    signed = decode_signature(signature)
    for key_id, public_key in trusted.items():
        if verify_ed25519_signature(bytes(public_key), signed, bytes(raw)):
            return str(key_id)
    raise ManifestSignatureError("подпись списка выпуска не сошлась", "sign")


def load_signed_manifest(
    raw: bytes,
    signature: bytes | str,
    *,
    trusted: Mapping[str, bytes] | None = None,
    product: str = PRODUCT,
) -> dict:
    """Проверенный манифест как dict. Подпись - до разбора JSON.

    Проверяет только то, что нужно клону для применения манифеста:
    подпись доверенным ключом, ``key`` в манифесте совпадает с подписавшим,
    ``product``/``channel``/``schema``/``version``/``files``. Версию новее
    установленной здесь не требует: проверка обновлений должна показывать
    и текущую версию, а не падать на ней.
    """
    if trusted is None:
        trusted = TRUSTED_KEYS
    key_id = signing_key_id(raw, signature, trusted)
    try:
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestSignatureError(f"список выпуска не читается: {exc}", "format") from None
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        raise ManifestSignatureError("список выпуска неизвестного вида", "format")
    if str(payload.get("key") or "") != key_id:
        raise ManifestSignatureError("список выпуска подписан не тем ключом, что в нём назван", "key")
    if str(payload.get("product") or "") != product:
        raise ManifestSignatureError(
            f"список выпуска для {payload.get('product')}, а нужен {product}", "product"
        )
    if str(payload.get("channel") or "") not in CHANNELS:
        raise ManifestSignatureError(
            f"список выпуска для канала {payload.get('channel')!r}, а нужен один из {CHANNELS}", "product"
        )
    if not str(payload.get("version") or ""):
        raise ManifestSignatureError("в списке выпуска нет версии", "format")
    if not isinstance(payload.get("files"), list):
        raise ManifestSignatureError("в списке выпуска нет списка файлов", "format")
    return payload


def dumps_manifest(payload: dict) -> bytes:
    """Байты манифеста: одинаковые при одинаковом содержании (как в оригинале)."""
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1) + "\n").encode("utf-8")


__all__ = [
    "CHANNELS",
    "MANIFEST_NAME",
    "MAX_MANIFEST_BYTES",
    "MAX_SIGNATURE_BYTES",
    "PRODUCT",
    "SIGNATURE_NAME",
    "TRUSTED_KEYS",
    "ManifestSignatureError",
    "decode_signature",
    "dumps_manifest",
    "load_signed_manifest",
    "signing_key_id",
]
