from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)


def _rate_limit_wait(r: httpx.Response, attempt: int) -> int:
    retry_after = r.headers.get("retry-after", "")
    reset = r.headers.get("x-ratelimit-reset", "")
    if retry_after.isdigit():
        wait = int(retry_after)
    elif r.headers.get("x-ratelimit-remaining") == "0" and reset.isdigit():
        wait = int(reset) - int(time.time()) + 1
    else:
        wait = 10 * (2 ** attempt)
    return max(1, min(wait, 120))


def get_json(
    client: httpx.Client,
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    max_retries: int = 5,
) -> dict | None:
    """GET with retry/backoff and rate-limit handling. Returns None on give-up."""
    for attempt in range(max_retries):
        try:
            r = client.get(url, params=params, headers=headers)
        except httpx.TransportError as exc:
            wait = 2 ** attempt
            log.warning("network error (%s); retrying in %ss", exc, wait)
            time.sleep(wait)
            continue

        if r.status_code == 200:
            return r.json()
        if r.status_code == 422:  # GitHub: bad query or beyond the 1000-result cap
            log.warning("422 for params=%s: %s", params, r.text[:160])
            return None
        if r.status_code in (403, 429):
            wait = _rate_limit_wait(r, attempt)
            log.warning("rate limited (%s); sleeping %ss", r.status_code, wait)
            time.sleep(wait)
            continue
        if r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        log.error("HTTP %s: %s", r.status_code, r.text[:160])
        return None

    log.error("giving up on %s", url)
    return None
