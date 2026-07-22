"""Firebase ID-token verification and stable internal identity mapping.

Every Firebase UID is mapped case-sensitively with UUIDv5. Imported users can
retain an existing ``app_users.id`` only through the signed, canonical UUID
custom claim documented below. Changing the namespace is database-breaking.
"""
from __future__ import annotations

import base64
import json
from typing import Any
from urllib.parse import urlparse
from uuid import UUID, uuid5

from firebase_admin import auth as firebase_auth

from app.repositories.supabase_http import AuthUser, SupabaseHttpError
from app.services.push_notifications import _firebase_app

# greeneatGo Firebase Authentication -> app_users identity namespace.
FIREBASE_UID_NAMESPACE = UUID("ad2bd92b-c52f-4b30-bb59-4f789edbcdb0")
INTERNAL_ID_CLAIM = "greeneatgo_internal_id"


def firebase_uid_to_internal_uuid(uid: str) -> str:
    """Deterministically map the exact, case-sensitive Firebase UID to UUIDv5."""
    return str(uuid5(FIREBASE_UID_NAMESPACE, uid))


def _internal_id(claims: dict[str, Any], uid: str) -> str:
    """Use a signed imported ID claim, or map the exact Firebase UID."""
    if INTERNAL_ID_CLAIM not in claims:
        return firebase_uid_to_internal_uuid(uid)

    claimed_id = claims[INTERNAL_ID_CLAIM]
    if not isinstance(claimed_id, str):
        raise SupabaseHttpError(401, "Firebase internal identity claim is invalid")
    try:
        parsed = UUID(claimed_id)
    except ValueError as exc:
        raise SupabaseHttpError(
            401, "Firebase internal identity claim is invalid"
        ) from exc
    # UUID() accepts upper-case, braces, compact strings, and other aliases.
    # Only the canonical lower-case hyphenated representation is permitted.
    if str(parsed) != claimed_id:
        raise SupabaseHttpError(401, "Firebase internal identity claim is invalid")
    return claimed_id


def _unverified_issuer(access_token: str) -> str | None:
    """Read only the issuer routing hint; this does not authenticate the JWT."""
    try:
        payload_segment = access_token.split(".")[1]
        padding = "=" * (-len(payload_segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_segment + padding))
    except (IndexError, ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    issuer = payload.get("iss") if isinstance(payload, dict) else None
    return issuer if isinstance(issuer, str) else None


def is_firebase_token(access_token: str) -> bool:
    issuer = _unverified_issuer(access_token)
    if issuer == "securetoken.google.com":
        return True
    try:
        return bool(issuer and urlparse(issuer).hostname == "securetoken.google.com")
    except ValueError:
        return False


def _safe_metadata(claims: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    for key in ("name", "picture", "phone_number"):
        value = claims.get(key)
        if isinstance(value, str):
            metadata[key] = value
    if "phone_number" in metadata:
        metadata["phone"] = metadata["phone_number"]
    firebase_claim = claims.get("firebase")
    if isinstance(firebase_claim, dict):
        provider = firebase_claim.get("sign_in_provider")
        if isinstance(provider, str):
            metadata["sign_in_provider"] = provider
    return metadata


def verify_firebase_auth_user(access_token: str) -> AuthUser:
    """Verify a Firebase token without ever falling back to Supabase."""
    try:
        app = _firebase_app()
        claims = firebase_auth.verify_id_token(
            access_token, app=app, check_revoked=True
        )
    except (firebase_auth.InvalidIdTokenError, firebase_auth.UserDisabledError) as exc:
        raise SupabaseHttpError(401, "Firebase ID token validation failed") from exc
    except Exception as exc:
        # Configuration, certificate fetch, transport, and internal verifier
        # failures are operational. Never leak certificate or credential detail.
        raise SupabaseHttpError(503, "Firebase authentication is unavailable") from exc

    email = claims.get("email")
    if (
        not isinstance(email, str)
        or not email.strip()
        or claims.get("email_verified") is not True
    ):
        raise SupabaseHttpError(401, "Firebase email is not verified")
    email = email.strip()
    uid = claims.get("uid") or claims.get("sub")
    if not isinstance(uid, str) or not uid:
        raise SupabaseHttpError(401, "Firebase ID token has no UID")
    return AuthUser(
        id=_internal_id(claims, uid),
        email=email,
        metadata=_safe_metadata(claims),
    )
