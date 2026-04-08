import hashlib
import re
import uuid


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def normalize_mobile(mobile: str) -> str:
    return re.sub(r"\D+", "", mobile.strip())


def validate_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def validate_mobile(mobile: str) -> bool:
    return len(normalize_mobile(mobile)) >= 10


def new_api_key() -> str:
    # Public-ish format; treat as secret.
    return f"berum_{uuid.uuid4().hex}{uuid.uuid4().hex}"

