"""Existing input rules and identifiers, independent of the HTTP entry point."""
import math
from datetime import datetime, timezone
from uuid import uuid4

from kanpace.core.errors import APIError


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def uid(prefix):
    return prefix + '_' + uuid4().hex[:12]


def number(value, name, *, positive=False, maximum=1e9):
    if isinstance(value, bool):
        raise APIError(400, name + ' 必须为数值')
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise APIError(400, name + ' 必须为数值')
    if not math.isfinite(result) or result < 0 or (positive and result <= 0) or result > maximum:
        raise APIError(400, name + ' 数值不在有效范围内')
    return result


def short_text(value, name, required=False, limit=1000):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise APIError(400, name + ' 必须为文字')
    value = value.strip()
    if len(value) > limit or (required and not value):
        raise APIError(400, name + ' 为空或过长')
    return value


def whole_number(value, name, maximum=1000000000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= maximum or not math.isfinite(value) or not float(value).is_integer():
        raise APIError(400, name + ' 必须为有效范围内的非负整件数/整数')
    return int(value)
