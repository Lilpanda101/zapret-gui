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
import bz2
import json
from collections.abc import Mapping

from ed25519 import verify_ed25519_signature

PRODUCT = "zapret-gui"
CHANNELS = ("dev", "stable")


class BsdiffError(ValueError):
    """Ошибка при наложении bsdiff дельта-патча."""
    pass


def _offtin(b: bytes) -> int:
    return int.from_bytes(b, byteorder="little", signed=True)


def _offtout(x: int) -> bytes:
    return x.to_bytes(8, byteorder="little", signed=True)


def apply_bsdiff(old: bytes, patch: bytes, expected_size: int | None = None) -> bytes:
    """
    Применяет дельта-патч в формате BSDIFF40 к байтам old.
    Реализация на чистом Python без внешних бинарей.
    """
    if len(patch) < 32 or patch[:8] != b"BSDIFF40":
        raise BsdiffError("Это не заплатка bsdiff (неверная сигнатура)")
    ctrl_len = _offtin(patch[8:16])
    diff_len = _offtin(patch[16:24])
    new_size = _offtin(patch[24:32])

    if ctrl_len < 0 or diff_len < 0 or new_size < 0 or 32 + ctrl_len + diff_len > len(patch):
        raise BsdiffError("Заголовок заплатки bsdiff повреждён")
    if expected_size is not None and new_size != expected_size:
        raise BsdiffError(f"Размер после заплатки ({new_size}) не совпадает с ожидаемым ({expected_size})")

    try:
        ctrl_raw = bz2.decompress(patch[32 : 32 + ctrl_len])
        diff_raw = bz2.decompress(patch[32 + ctrl_len : 32 + ctrl_len + diff_len])
        extra_raw = bz2.decompress(patch[32 + ctrl_len + diff_len :])
    except Exception as exc:
        raise BsdiffError(f"Ошибка распаковки bz2 блоков заплатки: {exc}") from exc

    if len(ctrl_raw) % 24 != 0:
        raise BsdiffError("Блок управления заплатки bsdiff повреждён (длина не кратна 24)")

    out = bytearray(new_size)
    old_pos = 0
    new_pos = 0
    d_pos = 0
    e_pos = 0
    old_len = len(old)

    for i in range(0, len(ctrl_raw), 24):
        cp = _offtin(ctrl_raw[i : i + 8])
        ex = _offtin(ctrl_raw[i + 8 : i + 16])
        sk = _offtin(ctrl_raw[i + 16 : i + 24])

        if cp < 0 or ex < 0:
            raise BsdiffError("Отрицательное смещение в блоке управления bsdiff")
        if new_pos + cp + ex > new_size:
            raise BsdiffError("Заплатка bsdiff выходит за размер целевого файла")

        for j in range(cp):
            ob = old[old_pos + j] if 0 <= old_pos + j < old_len else 0
            out[new_pos + j] = (ob + diff_raw[d_pos + j]) & 0xFF
        new_pos += cp
        old_pos += cp
        d_pos += cp

        out[new_pos : new_pos + ex] = extra_raw[e_pos : e_pos + ex]
        new_pos += ex
        e_pos += ex
        old_pos += sk

    if new_pos != new_size:
        raise BsdiffError(f"Заплатка собрала {new_pos} байт вместо ожидаемых {new_size}")
    return bytes(out)

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
    "BsdiffError",
    "apply_bsdiff",
    "decode_signature",
    "dumps_manifest",
    "load_signed_manifest",
    "signing_key_id",
]
