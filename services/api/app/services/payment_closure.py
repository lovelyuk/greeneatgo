import re
from datetime import datetime
from uuid import UUID


def public_closure(row: dict, status: str) -> dict | None:
    """Fail closed on malformed storage; never expose raw evidence to customers."""
    try:
        UUID(row['id'])
        stamp = datetime.fromisoformat(row['closed_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or row['outcome'] != status or not re.fullmatch('[a-f0-9]{64}', row['evidence_sha256']):
            return None
        return {key: row[key] for key in ('id','evidence_sha256','outcome','closed_at')} | {'scope':'order','finality':'verified'}
    except (KeyError, TypeError, ValueError, AttributeError):
        return None
