"""Push completed PRISMA review results to BrainKB's Oxigraph triplestore.

Wraps :class:`synthscholar.ontology.rdf_push.GraphDBConfig` with BrainKB's
existing ``GRAPHDATABASE_*`` env-var conventions (the same vars the
query_service already uses) so a unified configuration drives both services.

For long-running reviews (6-8 hours) the push happens once at the very end,
when the asyncio task calls ``mark_completed``. To survive large RDF
serialisations and transient network blips, the push uses a configurable
timeout and retries with exponential backoff.

Environment variables consumed
------------------------------

============================================  ===========================================
``GRAPHDATABASE_USERNAME``                    Basic-auth username (default ``admin``).
``GRAPHDATABASE_PASSWORD``                    Basic-auth password.
``GRAPHDATABASE_HOSTNAME``                    Bare hostname (``oxigraph``) or full URL
                                              (``https://db.brainkb.org``).  Default
                                              ``oxigraph`` (internal docker hostname).
``GRAPHDATABASE_PORT``                        Default ``7878``.
``GRAPHDATABASE_TYPE``                        Informational; only ``OXIGRAPH`` triggers
                                              the GSP path. Default ``OXIGRAPH``.
``SYNTH_SCHOLAR_PUSH_TO_GRAPHDB``             Feature flag (``true``/``false``).
                                              Default ``true`` — set to ``false`` to
                                              disable the push without unsetting creds.
``SYNTH_SCHOLAR_GRAPHDB_PATH``                Endpoint path (default ``/store`` for GSP,
                                              use ``/update`` for SPARQL Update).
``SYNTH_SCHOLAR_GRAPHDB_NAMED_GRAPH_PREFIX``  IRI prefix for review-specific named graphs.
                                              Default ``https://brainkb.org/reviews/``.
                                              Each review lands at ``{prefix}{review_id}``.
``SYNTH_SCHOLAR_GRAPHDB_PROTOCOL``            ``gsp`` (default) or ``update``.
``SYNTH_SCHOLAR_GRAPHDB_REPLACE``             If ``true``, replace the named graph each
                                              run (HTTP PUT). Default ``true`` — review
                                              IDs are stable, so a re-run should overwrite.
``SYNTH_SCHOLAR_GRAPHDB_TIMEOUT``             HTTP timeout in seconds for one push attempt.
                                              Default ``600`` (10 min) — generous because
                                              large reviews can produce megabytes of TTL.
``SYNTH_SCHOLAR_GRAPHDB_MAX_RETRIES``         Total attempts including the first.
                                              Default ``3``. Backoff is 5 / 30 / 120 s.
============================================  ===========================================
"""

from __future__ import annotations

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

# Backoff schedule (seconds) for retries — index 0 is unused (first attempt
# never sleeps). Anything past len(_BACKOFF) clamps to the last value.
_BACKOFF = [0, 5, 30, 120, 300]


def _truthy(val: Optional[str], default: bool = False) -> bool:
    if val is None or val == "":
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def _build_endpoint() -> Optional[str]:
    """Compose the Oxigraph endpoint URL from BrainKB's GRAPHDATABASE_* vars."""
    host = (os.getenv("GRAPHDATABASE_HOSTNAME") or "oxigraph").strip()
    port = (os.getenv("GRAPHDATABASE_PORT") or "7878").strip()
    path = (os.getenv("SYNTH_SCHOLAR_GRAPHDB_PATH") or "/store").strip()
    if not path.startswith("/"):
        path = "/" + path

    if not host:
        return None

    # Accept full URL ("https://db.brainkb.org[:port]") or bare hostname ("oxigraph").
    if host.startswith(("http://", "https://")):
        # Don't append port if it's already in the URL.
        from urllib.parse import urlparse
        parsed = urlparse(host)
        if parsed.port is None and port:
            base = f"{host.rstrip('/')}:{port}"
        else:
            base = host.rstrip("/")
    else:
        base = f"http://{host.rstrip('/')}:{port}"
    return base + path


def _make_config():
    """Build a ``GraphDBConfig`` from BrainKB env vars, or None if disabled.

    Returns ``None`` (without raising) when the push is disabled, when the
    optional ``synthscholar`` import fails, or when no usable endpoint can
    be composed.
    """
    if not _truthy(os.getenv("SYNTH_SCHOLAR_PUSH_TO_GRAPHDB"), default=True):
        return None

    try:
        from synthscholar.ontology.rdf_push import GraphDBConfig  # type: ignore[import-not-found]
    except Exception as exc:
        logger.warning("[oxigraph_push] synthscholar.rdf_push unavailable: %s", exc)
        return None

    endpoint = _build_endpoint()
    if not endpoint:
        return None

    timeout_env = os.getenv("SYNTH_SCHOLAR_GRAPHDB_TIMEOUT")
    try:
        timeout = float(timeout_env) if timeout_env else 600.0
    except ValueError:
        logger.warning(
            "[oxigraph_push] invalid SYNTH_SCHOLAR_GRAPHDB_TIMEOUT=%r — using 600s",
            timeout_env,
        )
        timeout = 600.0

    return GraphDBConfig(
        endpoint=endpoint,
        user=os.getenv("GRAPHDATABASE_USERNAME") or None,
        password=os.getenv("GRAPHDATABASE_PASSWORD") or None,
        protocol=(os.getenv("SYNTH_SCHOLAR_GRAPHDB_PROTOCOL") or "gsp").lower(),
        replace=_truthy(os.getenv("SYNTH_SCHOLAR_GRAPHDB_REPLACE"), default=True),
        timeout=timeout,
    )


def _named_graph_for(review_id: str) -> str:
    """IRI for the named graph holding *review_id*'s triples."""
    prefix = os.getenv(
        "SYNTH_SCHOLAR_GRAPHDB_NAMED_GRAPH_PREFIX",
        "https://brainkb.org/reviews/",
    )
    if not prefix.endswith("/"):
        prefix += "/"
    return prefix + review_id


def _is_retryable(exc: BaseException) -> bool:
    """True for transient failures worth retrying (network, 5xx, 429)."""
    try:
        import httpx
    except Exception:
        return False
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or 500 <= code < 600  # rate-limited or server error
    return False


def push_review_to_oxigraph(review_id: str, result) -> Optional[int]:
    """Best-effort push of a completed review's RDF to BrainKB's Oxigraph.

    Returns the HTTP status code on success, or ``None`` if the push was
    skipped or failed. **Never raises** — failures are logged at WARNING and
    must not affect the review's recorded status in Postgres.

    For long-running reviews the RDF is built once (in-memory) and then the
    HTTP push is retried with exponential backoff on transient failures
    (timeouts, 5xx, 429). Auth and schema errors fail fast on the first try.

    Parameters
    ----------
    review_id:
        The review's stable ID, used to compose the named-graph IRI.
    result:
        A ``PRISMAReviewResult`` (or anything ``synthscholar.export.to_oxigraph_store``
        accepts). Passed by reference; not mutated.
    """
    if result is None:
        logger.debug("[oxigraph_push] no result to push for %s", review_id)
        return None

    cfg = _make_config()
    if cfg is None:
        logger.debug("[oxigraph_push] push disabled or not configured for %s", review_id)
        return None

    cfg.named_graph = _named_graph_for(review_id)

    try:
        max_retries = max(1, int(os.getenv("SYNTH_SCHOLAR_GRAPHDB_MAX_RETRIES") or 3))
    except ValueError:
        max_retries = 3

    # Serialise once — retries reuse the same store, so we don't pay the
    # rdflib → pyoxigraph conversion cost on every attempt.
    try:
        from synthscholar.export import to_oxigraph_store  # type: ignore[import-not-found]
        store = to_oxigraph_store(result)
    except Exception as exc:
        logger.warning(
            "[oxigraph_push] failed to serialise review %s: %s", review_id, exc,
        )
        return None

    last_exc: Optional[BaseException] = None
    for attempt in range(1, max_retries + 1):
        try:
            status = store.push_with_config(cfg)
            if attempt > 1:
                logger.info(
                    "[oxigraph_push] pushed review %s on attempt %d/%d to %s "
                    "(graph <%s>) — HTTP %s",
                    review_id, attempt, max_retries,
                    cfg.resolved_endpoint, cfg.named_graph, status,
                )
            else:
                logger.info(
                    "[oxigraph_push] pushed review %s to %s (graph <%s>) — HTTP %s",
                    review_id, cfg.resolved_endpoint, cfg.named_graph, status,
                )
            return status
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable(exc):
                break
            sleep_s = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            logger.warning(
                "[oxigraph_push] attempt %d/%d failed for review %s "
                "(retrying in %ds): %s",
                attempt, max_retries, review_id, sleep_s, exc,
            )
            time.sleep(sleep_s)

    logger.warning(
        "[oxigraph_push] giving up on review %s after %d attempt(s) "
        "(endpoint=%s graph=%s): %s",
        review_id, max_retries, cfg.resolved_endpoint, cfg.named_graph, last_exc,
    )
    return None
