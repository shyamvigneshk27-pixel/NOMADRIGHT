"""
Shared helpers for the BHASHINI model adapters (asr.py, nmt.py, tts.py).

All three adapters talk to a single local model service, bhashini_models.service,
provisioned entirely offline via rootfs/roles/indic during image build (CTranslate2
ASR/NMT engines + Flite TTS, compiled and cached on-device). No adapter in this
package ever reaches out past localhost - this module is the one place that
constructs the base URL, so that guarantee is easy to audit.
"""

import logging
from subprocess import run
from typing import Any, Dict, Tuple

import requests

BHASHINI_HOST = "localhost"
BHASHINI_PORT = 11400
DEFAULT_TIMEOUT = 15.0
HEALTH_TIMEOUT = 3.0

logger = logging.getLogger(__name__)


def base_url(host: str = BHASHINI_HOST, port: int = BHASHINI_PORT) -> str:
    return f"http://{host}:{port}"


def verify_service(service_label: str) -> Tuple[bool, str]:
    """Checks that bhashini_models.service is up and answering /health."""
    try:
        resp = requests.get(f"{base_url()}/health", timeout=HEALTH_TIMEOUT)
        if resp.ok:
            return True, f"{service_label}: BHASHINI model service healthy"
        return False, f"{service_label}: BHASHINI health check returned HTTP {resp.status_code}"
    except Exception as exc:
        return False, f"{service_label}: BHASHINI model service unreachable ({exc})"


def restart_service(service_label: str) -> bool:
    """
    Restarts the local bhashini_models.service via systemctl.

    This never downloads anything - all BHASHINI weights are baked into the
    rootfs image offline (rootfs/roles/indic). If the service still isn't
    healthy after a restart, callers should surface a clear configuration
    error rather than silently retrying forever.
    """
    try:
        run(["systemctl", "restart", "bhashini_models.service"], check=False, timeout=30)
        return True
    except Exception as exc:
        logger.warning(f"{service_label}: could not restart bhashini_models.service: {exc}")
        return False
