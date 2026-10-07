# core/reality.py
from __future__ import annotations

import secrets
from core.ssh_client import XrayServer, SSHError


class RealityKeyError(Exception):
    pass


def generate_keypair(ssh: XrayServer) -> tuple[str, str]:
    result = ssh.run("/usr/local/bin/xray x25519", warn=True)
    if result.failed:
        raise RealityKeyError(f"xray x25519 провалился:\n{result.stderr}")

    output = result.stdout or ""
    private_key = None
    public_key = None

    private_markers = ["Private key:", "PrivateKey:"]
    public_markers = [
        "Public key:", "Password (PublicKey):",
        "Password(PublicKey):", "PublicKey:"
    ]

    for line in output.splitlines():
        for m in private_markers:
            if m in line and private_key is None:
                private_key = line.split(m, 1)[-1].strip()
        for m in public_markers:
            if m in line and public_key is None:
                public_key = line.split(m, 1)[-1].strip()

    if not private_key or not public_key:
        raise RealityKeyError(f"Не удалось распарсить вывод:\n{output}")

    return private_key, public_key


def generate_short_id() -> str:
    return secrets.token_hex(8)