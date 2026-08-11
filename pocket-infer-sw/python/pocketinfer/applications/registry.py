
class ApplicationRegistry:
    _classes = {}
    _metadata = {}

    @classmethod
    def register(cls, app_cls, metadata):
        cls._classes[app_cls.__name__] = app_cls
        cls._metadata[app_cls.__name__] = metadata
        if metadata and "name" in metadata:
            cls._classes[metadata["name"]] = app_cls
            cls._metadata[metadata["name"]] = metadata

    @classmethod
    def get_application(cls, name):
        return cls._classes.get(name)
    
    @classmethod
    def get_metadata(cls, name):
        return cls._metadata.get(name)  

class RegisterApplication:
    def __init__(self, metadata):
        self.metadata = metadata

    def __call__(self, app_cls):
        ApplicationRegistry.register(app_cls, self.metadata)
        app_cls.METADATA = self.metadata
        return app_cls
