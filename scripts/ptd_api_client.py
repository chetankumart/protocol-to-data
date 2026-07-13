#!/usr/bin/env python3
"""Call the protocol-to-data API with a one-retry on transient free-tier errors.

Render's **free tier** can transiently drop the SSE stream (raising ``CancelledError``) or reset
the connection when a worker is busy or restarts between requests. ``predict_with_retry`` retries
such *transient* failures once by default, so a single blip doesn't fail your call. Genuine errors
(bad input, a server-side exception) are **not** retried — they propagate immediately.

Client-side helper only — it does not import or touch the app / ``src/``.

Usage:
    from gradio_client import Client, handle_file
    from ptd_api_client import predict_with_retry   # (scripts/ on sys.path)

    client = Client("https://protocol-to-data.onrender.com")
    zip_path = predict_with_retry(
        client,
        file_path=handle_file("my_protocol.pdf"), use_sample=False,
        subjects=40, seed=42, anomalies=0,
        export_format="SDTM (Parquet) - Databricks Analytics Ready", protocol_url="",
        api_name="/download_synthetic_data",
    )
"""
from __future__ import annotations

import concurrent.futures
import time

# Transient failures observed on the 512MB free tier: SSE cancellation + connection resets.
# Deliberately NOT included: AppError / ValueError / TypeError — those are real errors that must
# surface immediately, never retried.
TRANSIENT_ERRORS: tuple[type[BaseException], ...] = (
    concurrent.futures.CancelledError,
    ConnectionError,
)


def predict_with_retry(client, *args, retries: int = 1, backoff: float = 3.0,
                       transient: tuple[type[BaseException], ...] = TRANSIENT_ERRORS, **kwargs):
    """``client.predict(*args, **kwargs)`` with up to ``retries`` retries on transient errors.

    Sleeps ``backoff`` seconds between attempts. Re-raises the last transient error once retries
    are exhausted; non-transient errors are never retried.
    """
    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return client.predict(*args, **kwargs)
        except transient as exc:
            last = exc
            if attempt < retries:
                time.sleep(backoff)
    raise last  # type: ignore[misc]  — only reached after a transient error set `last`
