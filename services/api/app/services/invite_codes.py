"""Company invite codes (audit M5).

Codes used to be ``GE-`` + 3 random bytes (24 bits, ~16.7M values), small
enough to enumerate through /v1/join/request. New codes carry 50 bits from an
unambiguous alphabet (no 0/O/1/I) and stay easy to type: GE-XXXXX-XXXXX.
"""

import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def new_company_invite_code() -> str:
    chars = "".join(secrets.choice(ALPHABET) for _ in range(10))
    return f"GE-{chars[:5]}-{chars[5:]}"
