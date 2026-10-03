"""Keeps the user's position and walking speed out of uvicorn's request logs.

uvicorn's access log prints each request's full path with its query string, and at its trace level the
`uvicorn.asgi` logger prints the raw ASGI scope, including `query_string`. The page sends coordinates and a
walking speed in the query, so these filters remove those parameters from the logged records. The request
itself is untouched, and the path and the other parameters stay so the logs remain useful. The filters only
cover this app's own logging: a hosting proxy can still record URLs.
"""

import logging

PRIVATE_QUERY_PARAMS = frozenset(
    {
        "walk_speed",
        "walk_speed_source",
        "lat",
        "lon",
        "user_lat",
        "user_lon",
        "accuracy",
        "location_timestamp",
    }
)

# The loggers that can carry a request's query: the access log, uvicorn's error log, and its trace-level ASGI log.
FILTERED_LOGGERS = ("uvicorn.access", "uvicorn.error", "uvicorn.asgi")


def _keep(part: str) -> bool:
    return part.split("=", 1)[0] not in PRIVATE_QUERY_PARAMS


def strip_private_query_string(query: str) -> str:
    """A query string without the private parameters."""
    return "&".join(part for part in query.split("&") if _keep(part))


def strip_private_query(path: str) -> str:
    """A path with its private query parameters removed (the rest of the query stays)."""
    base, separator, query = path.partition("?")
    if not separator:
        return path
    kept = strip_private_query_string(query)
    return base + ("?" + kept if kept else "")


def _strip_text(value):
    """str or bytes: the query part with the private parameters removed."""
    if isinstance(value, bytes):
        return strip_private_query(value.decode("latin-1")).encode("latin-1")
    return strip_private_query(value)


def clean_asgi_value(value):
    """A copy of an ASGI scope or message with the private query values removed. Other fields stay."""
    if not isinstance(value, dict):
        return value
    cleaned = {}
    for key, item in value.items():
        if key == "query_string" and isinstance(item, (bytes, str)):
            if isinstance(item, bytes):
                cleaned[key] = strip_private_query_string(item.decode("latin-1")).encode("latin-1")
            else:
                cleaned[key] = strip_private_query_string(item)
        elif isinstance(item, (bytes, str)) and (b"?" in item if isinstance(item, bytes) else "?" in item):
            cleaned[key] = _strip_text(item)  # raw_path, path or any other field that carries a query
        else:
            cleaned[key] = item
    return cleaned


class StripPrivateQuery(logging.Filter):
    """Removes the private parameters from every string argument that holds a path with a query."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple):
            record.args = tuple(
                strip_private_query(item) if isinstance(item, str) and "?" in item else item for item in args
            )
        elif isinstance(record.msg, str) and "?" in record.msg:
            record.msg = strip_private_query(record.msg)
        return True


class StripAsgiQuery(logging.Filter):
    """Cleans the ASGI scope and message that uvicorn's trace-level logger prints."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(clean_asgi_value(item) for item in record.args)
        return True


def install() -> None:
    """Add the filters once to uvicorn's request loggers (safe to call again)."""
    for name in FILTERED_LOGGERS:
        logger = logging.getLogger(name)
        for filter_class in (StripPrivateQuery, StripAsgiQuery):
            if not any(isinstance(existing, filter_class) for existing in logger.filters):
                logger.addFilter(filter_class())
