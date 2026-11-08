import hashlib
import hmac
import subprocess
import sys
from pathlib import Path
import pytest

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDFExpand
from cryptography.hazmat.primitives import hashes

import fake_generator as fg

INITIAL_SALT_V1 = bytes.fromhex("38762cf7f55934b34d179ae6a4c80cadccbb7f0a")


def hkdf_label(sec, label_str, ctx, out_len):
    lbl = b"tls13 " + label_str.encode()
    hkdf_info = out_len.to_bytes(2, "big") + len(lbl).to_bytes(1, "big") + lbl + len(ctx).to_bytes(1, "big") + ctx
    return HKDFExpand(algorithm=hashes.SHA256(), length=out_len, info=hkdf_info).derive(sec)


def decrypt_quic_packet(pkt: bytes) -> tuple[bytes, bytes]:
    """Helper to decrypt RFC 9000/9001 Initial packet and return (plaintext, dcid)."""
    assert (pkt[0] & 0x80) != 0, "Not a long header"
    dcid_len = pkt[5]
    dcid = pkt[6 : 6 + dcid_len]
    scid_len = pkt[6 + dcid_len]
    offset = 7 + dcid_len + scid_len
    # Token length varint
    token_len = pkt[offset]
    offset += 1 + token_len
    # Length varint
    v_b = pkt[offset]
    if (v_b & 0xC0) == 0x40:
        length_field = ((v_b & 0x3F) << 8) | pkt[offset + 1]
        offset += 2
    else:
        length_field = v_b
        offset += 1

    pn_len = (pkt[0] & 0x03) + 1
    sample = pkt[offset + 4 : offset + 20]

    initial_secret = hmac.new(INITIAL_SALT_V1, dcid, hashlib.sha256).digest()
    client_secret = hkdf_label(initial_secret, "client in", b"", 32)
    key = hkdf_label(client_secret, "quic key", b"", 16)
    iv = hkdf_label(client_secret, "quic iv", b"", 12)
    hp = hkdf_label(client_secret, "quic hp", b"", 16)

    mask = Cipher(algorithms.AES(hp), modes.ECB()).encryptor().update(sample)
    unmasked_first = pkt[0] ^ (mask[0] & 0x0F)
    actual_pn_len = (unmasked_first & 0x03) + 1

    pn_bytes = bytearray(pkt[offset : offset + actual_pn_len])
    for i in range(actual_pn_len):
        pn_bytes[i] ^= mask[1 + i]

    unmasked_hdr = bytes([unmasked_first]) + pkt[1:offset] + bytes(pn_bytes)
    ciphertext = pkt[offset + actual_pn_len : offset + length_field]

    nonce = bytearray(iv)
    for i in range(actual_pn_len):
        nonce[-1 - i] ^= pn_bytes[-1 - i]

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(bytes(nonce), ciphertext, unmasked_hdr)
    return plaintext, dcid


def test_tls_client_hello_generation():
    test_domains = ["cloudflare.com", "rutracker.org", "googlevideo.com"]
    for dom in test_domains:
        # 1. Kyber
        ch_kyber = fg.build_tls_client_hello(dom, kyber=True)
        assert ch_kyber[:3] == b"\x16\x03\x01"
        assert ch_kyber[5] == 0x01
        assert dom.encode() in ch_kyber
        assert len(ch_kyber) > 1700

        # 2. Non-Kyber
        ch_nokyber = fg.build_tls_client_hello(dom, kyber=False)
        assert ch_nokyber[:3] == b"\x16\x03\x01"
        assert dom.encode() in ch_nokyber
        assert len(ch_nokyber) < 700


def test_quic_initial_generation_and_decryption():
    dom = "speedtest.net"
    # Non-kyber single packet
    packets = fg.build_quic_initial_packets(dom, kyber=False, target_size=1200)
    assert len(packets) == 1
    assert len(packets[0]) == 1200

    plaintext, dcid = decrypt_quic_packet(packets[0])
    assert dom.encode() in plaintext
    assert plaintext[0] == 0x06  # CRYPTO frame

    # Kyber multi-packet (2 packets of 1230 bytes)
    k_pkts = fg.build_quic_initial_packets(dom, kyber=True)
    assert len(k_pkts) == 2
    assert len(k_pkts[0]) == 1230
    assert len(k_pkts[1]) == 1230

    pt1, dcid1 = decrypt_quic_packet(k_pkts[0])
    pt2, dcid2 = decrypt_quic_packet(k_pkts[1])
    # Both packets must share same DCID
    assert dcid1 == dcid2
    # Combined crypto stream must contain SNI
    combined = pt1 + pt2
    assert dom.encode() in combined


def test_cli_fake_generator(tmp_path):
    out_tls = tmp_path / "test_out_tls.bin"
    res = subprocess.run(
        [sys.executable, "fake_generator.py", "mycustomsite.org", "--mode", "tls", "-o", str(out_tls)],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert out_tls.is_file()
    assert b"mycustomsite.org" in out_tls.read_bytes()
