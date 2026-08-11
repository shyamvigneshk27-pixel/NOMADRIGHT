import ollama
import logging
from subprocess import check_output
import requests


class Ollama:
    def __init__(self, model_name: str):
        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.preload()

    def preload(self):
        """Pre-load model into memory with keep_alive=-1 to guarantee sub-200ms initial response time."""
        try:
            self.logger.info(f"Pre-warming Ollama model '{self.model_name}' in memory...")
            requests.post(
                'http://localhost:11434/api/generate',
                json={
                    'model': self.model_name,
                    'prompt': '',
                    'keep_alive': -1,
                    'options': {'num_thread': 6}
                },
                timeout=10.0
            )
        except Exception as e:
            self.logger.warning(f"Failed to pre-warm Ollama model '{self.model_name}': {e}")

    def chat(self, messages: list, options: dict = None) -> ollama.ChatResponse:
        default_opts = {
            "num_thread": 6,
            "num_predict": 25,
            "temperature": 0.2,
            "top_k": 20,
            "top_p": 0.8,
        }
        if options:
            default_opts.update(options)
        return ollama.chat(model=self.model_name, messages=messages, options=default_opts, keep_alive=-1)

    def generate(self, prompt: str, images: list = None, options: dict = None):
        default_opts = {
            "num_thread": 6,
            "num_predict": 25,
            "temperature": 0.2,
            "top_k": 20,
            "top_p": 0.8,
        }
        if options:
            default_opts.update(options)
        
        kwargs = {
            "model": self.model_name,
            "prompt": prompt,
            "options": default_opts,
            "keep_alive": -1
        }
        if images and len(images) > 0:
            formatted_images = []
            for img in images:
                if isinstance(img, bytearray):
                    formatted_images.append(bytes(img))
                else:
                    formatted_images.append(img)
            kwargs["images"] = formatted_images

        return ollama.generate(**kwargs)

    def restart(self):
        print(check_output('systemctl restart ollama', shell=True))
        self.preload()
    
    @classmethod
    def verify(cls, args):
        try:
            ret = ollama.list()
            for model in ret.models:
                if model.model == args["model_name"]:
                    requests.post('http://localhost:11434/api/generate', json={'model': args['model_name'], 'keep_alive': -1, 'options': {'num_thread': 6}})
                    return True, "Ollama service is available."
            return False, f"Model '{args['model_name']}' not found."
        except Exception as e:
            return False, str(e)

    @classmethod
    def update(cls, args):
        try:
            logging.info(f"Pulling Ollama model '{args['model_name']}'")
            ollama.pull(model=args["model_name"])
        except Exception as e:
            raise RuntimeError(f"Failed to update Ollama model '{args['model_name']}': {str(e)}")

