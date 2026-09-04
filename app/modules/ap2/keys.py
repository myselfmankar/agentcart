"""Key management for AP2 cryptographic mandate signing.

Generates and persists EC P-256 JWK keys:
- Agent Provider Key: Represents the user/platform root authority that signs Open Mandates.
- Agent Key: Represents the autonomous Shopping Agent that signs Closed Mandates.
- Merchant Keys: Represents merchant identity for signing receipts.
"""

import json
import os
from pathlib import Path
from typing import Optional
from cryptography.hazmat.primitives.asymmetric import ec
from jwcrypto.jwk import JWK

_TEMP_DB = Path(os.environ.get("TEMP_DB_DIR", ".temp-db"))
_TEMP_DB.mkdir(parents=True, exist_ok=True)

AGENT_PROVIDER_KEY_PATH = _TEMP_DB / "agent_provider_key.json"
AGENT_PROVIDER_PUB_PATH = _TEMP_DB / "agent_provider_pub.json"
AGENT_KEY_PATH = _TEMP_DB / "agent_signing_key.json"
AGENT_PUB_PATH = _TEMP_DB / "agent_signing_pub.json"
MERCHANT_KEY_PATH = _TEMP_DB / "merchant_signing_key.json"
MERCHANT_PUB_PATH = _TEMP_DB / "merchant_signing_pub.json"


def _write_jwk(path: Path, jwk: JWK, public_only: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    export_data = jwk.export_public() if public_only else jwk.export()
    path.write_text(export_data, encoding="utf-8")


def _load_or_generate_key(private_path: Path, public_path: Path, kid: str) -> JWK:
    if private_path.exists():
        try:
            return JWK.from_json(private_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Generate new P-256 EC Key
    raw_key = ec.generate_private_key(ec.SECP256R1())
    jwk = JWK.from_pyca(raw_key)
    jwk_dict = json.loads(jwk.export())
    jwk_dict["kid"] = kid
    jwk = JWK.from_json(json.dumps(jwk_dict))

    _write_jwk(private_path, jwk, public_only=False)
    _write_jwk(public_path, jwk, public_only=True)
    return jwk


def get_agent_provider_key() -> JWK:
    """Return the user/platform root signing key used to sign Open Mandates."""
    return _load_or_generate_key(AGENT_PROVIDER_KEY_PATH, AGENT_PROVIDER_PUB_PATH, "agent-provider-key-1")


def get_agent_key() -> JWK:
    """Return the autonomous Shopping Agent key used to sign Closed Mandates."""
    return _load_or_generate_key(AGENT_KEY_PATH, AGENT_PUB_PATH, "agent-key-1")


def get_merchant_key(merchant_id: str = "merchant_c") -> JWK:
    """Return signing key for a given merchant."""
    priv_path = _TEMP_DB / f"{merchant_id}_priv.json"
    pub_path = _TEMP_DB / f"{merchant_id}_pub.json"
    return _load_or_generate_key(priv_path, pub_path, f"{merchant_id}-key-1")