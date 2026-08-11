"""
NomadRight Application Package

Encapsulates the 100% offline citizen welfare assistant running on
the Suno Sutra platform (NVIDIA Jetson Orin Nano).

Core pipeline modules (hardware-free, importable anywhere):
    NomadRightConfig    — runtime configuration dataclass
    WorkflowController  — Decision Layer pipeline orchestrator

Hardware-bound entry point (Jetson / Suno Sutra only):
    NomadRightApplication — registered BaseApplication subclass
    Imported lazily to avoid pulling in the audio/board stack on dev machines.
"""

from pocketinfer.applications.nomad_right.config import NomadRightConfig
from pocketinfer.applications.nomad_right.workflow import WorkflowController

__all__ = [
    "NomadRightConfig",
    "WorkflowController",
]

# Lazy import: only load the hardware-bound app class when actually needed.
# This avoids import errors from the audio/board stack on non-Jetson machines.
def _load_app():
    from pocketinfer.applications.nomad_right.app import NomadRightApplication  # noqa: F401
    return NomadRightApplication


# Allow `from pocketinfer.applications.nomad_right import NomadRightApplication`
# to still work at runtime on the Jetson.
def __getattr__(name: str):
    if name == "NomadRightApplication":
        return _load_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
