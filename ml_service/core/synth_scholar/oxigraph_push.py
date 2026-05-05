"""Push completed PRISMA review results to BrainKB's Oxigraph triplestore.

Wraps :class:`synthscholar.ontology.rdf_push.GraphDBConfig` with BrainKB's
existing ``GRAPHDATABASE_*`` env-var conventions (the same vars the
query_service already uses) so a unified configuration drives both services.

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
============================================  ===========================================
"""

from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


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

    return GraphDBConfig(
        endpoint=endpoint,
        user=os.getenv("GRAPHDATABASE_USERNAME") or None,
        password=os.getenv("GRAPHDATABASE_PASSWORD") or None,
        protocol=(os.getenv("SYNTH_SCHOLAR_GRAPHDB_PROTOCOL") or "gsp").lower(),
        replace=_truthy(os.getenv("SYNTH_SCHOLAR_GRAPHDB_REPLACE"), default=True),
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


def push_review_to_oxigraph(review_id: str, result) -> Optional[int]:
    """Best-effort push of a completed review's RDF to BrainKB's Oxigraph.

    Returns the HTTP status code on success, or ``None`` if the push was
    skipped or failed. **Never raises** — failures are logged at WARNING and
    must not affect the review's recorded status in Postgres.

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
        from synthscholar.export import to_oxigraph_store  # type: ignore[import-not-found]
        store = to_oxigraph_store(result)
        status = store.push_with_config(cfg)
        logger.info(
            "[oxigraph_push] pushed review %s to %s (graph <%s>) — HTTP %s",
            review_id, cfg.resolved_endpoint, cfg.named_graph, status,
        )
        return status
    except Exception as exc:
        logger.warning(
            "[oxigraph_push] failed for review %s (endpoint=%s graph=%s): %s",
            review_id, cfg.resolved_endpoint, cfg.named_graph, exc,
        )
        return None
