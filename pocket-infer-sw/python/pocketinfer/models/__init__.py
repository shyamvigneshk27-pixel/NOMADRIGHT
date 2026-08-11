"""
Suno Sutra Model Adapters

Each submodule wraps a single on-device model or local model service and
exposes a consistent contract used by BaseApplication.verify_dependencies():

    class <ModelName>:
        def __init__(self, **kwargs): ...
        @classmethod
        def verify(cls, args: dict) -> tuple[bool, str]: ...
        @classmethod
        def update(cls, args: dict) -> bool: ...
"""
