"""
NomadRight Configuration Module
"""

from dataclasses import dataclass
from typing import Dict, Any, Optional
from pocketinfer.applications.nomad_right import constants


@dataclass
class NomadRightConfig:
    """Dataclass holding all runtime configuration settings for NomadRight."""
    db_path: str = constants.DEFAULT_DB_PATH
    rules_dir: str = constants.DEFAULT_RULES_DIR
    log_dir: str = constants.DEFAULT_LOG_DIR
    offline_mode: bool = True

    # BHASHINI model service (ASR / NMT / TTS all served from here)
    bhashini_host: str = constants.BHASHINI_HOST
    bhashini_port: int = constants.BHASHINI_PORT

    # Language settings
    input_language: str = constants.DEFAULT_SOURCE_LANGUAGE    # worker's spoken language
    bridge_language: str = constants.DEFAULT_BRIDGE_LANGUAGE   # voice-bridge target language

    # RAG pipeline (ChromaDB + multilingual-e5-small)
    chroma_persist_dir: str = constants.DEFAULT_CHROMA_PERSIST_DIR
    chroma_collection_name: str = constants.CHROMA_COLLECTION_NAME
    embedding_model_name: str = constants.EMBEDDING_MODEL_NAME
    rag_top_k: int = constants.RAG_TOP_K

    max_response_length: str = "under sixty words"

    # Voice styling (male-leaning pitch shift + brisker tempo) - see
    # constants.TTS_VOICE_STYLE_ENABLED for why this exists instead of a
    # different voice file.
    voice_style_enabled: bool = constants.TTS_VOICE_STYLE_ENABLED

    @classmethod
    def from_settings(cls, settings: Optional[Dict[str, Any]] = None) -> "NomadRightConfig":
        """
        Creates a NomadRightConfig instance from a Suno Sutra application settings dictionary.

        Args:
            settings: Dictionary of configuration overrides passed from CLI or application manifest.

        Returns:
            NomadRightConfig instance initialized with parsed values.
        """
        if not settings:
            return cls()

        return cls(
            db_path=settings.get("db_path", constants.DEFAULT_DB_PATH),
            rules_dir=settings.get("rules_dir", constants.DEFAULT_RULES_DIR),
            log_dir=settings.get("log_directory", constants.DEFAULT_LOG_DIR),
            offline_mode=bool(settings.get("offline_mode", True)),
            bhashini_host=settings.get("bhashini_host", constants.BHASHINI_HOST),
            bhashini_port=int(settings.get("bhashini_port", constants.BHASHINI_PORT)),
            input_language=settings.get("input_language", constants.DEFAULT_SOURCE_LANGUAGE),
            bridge_language=settings.get("bridge_language", constants.DEFAULT_BRIDGE_LANGUAGE),
            chroma_persist_dir=settings.get("chroma_persist_dir", constants.DEFAULT_CHROMA_PERSIST_DIR),
            chroma_collection_name=settings.get("chroma_collection_name", constants.CHROMA_COLLECTION_NAME),
            embedding_model_name=settings.get("embedding_model_name", constants.EMBEDDING_MODEL_NAME),
            rag_top_k=int(settings.get("rag_top_k", constants.RAG_TOP_K)),
            max_response_length=settings.get("max_response_length", "under sixty words"),
            voice_style_enabled=cls._parse_bool(
                settings.get("voice_style_enabled", constants.TTS_VOICE_STYLE_ENABLED)
            ),
        )

    @staticmethod
    def _parse_bool(value: Any) -> bool:
        """Parses a bool that may arrive as an actual bool or a CLI string ("false"/"0")."""
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "")
        return bool(value)
