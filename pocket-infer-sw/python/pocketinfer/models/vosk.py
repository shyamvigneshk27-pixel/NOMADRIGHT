from vosk import KaldiRecognizer, Model
from speech_recognition import AudioData
from speech_recognition.cli import download_vosk_model
import json
import os
import logging
from appdirs import user_cache_dir
from pathlib import Path
from typing import TypedDict, cast


class VoskResponse(TypedDict):
    text: str

class Vosk:
    MODEL_DIR = Path(user_cache_dir("pocketinfer")) / "vosk_model"

    def __init__(self, model_name):
        self.logger = logging.getLogger(__name__)
        self.model_name = model_name
        self.model_path = os.path.join(self.MODEL_DIR, model_name)

    def recognize(self, audio_data: AudioData, verbose: bool = False) -> str:
        if not os.path.exists(self.model_path):
            raise RuntimeError(
                f"Vosk model not found at {self.model_path}. "
                "Please download the model using `sprc download vosk` command."
            )

        self.logger.debug(f"Recognizing audio data with Vosk model {self.model_name}")
        SAMPLE_RATE = 16_000
        rec = KaldiRecognizer(Model(self.model_path), SAMPLE_RATE)

        rec.AcceptWaveform(
            audio_data.get_raw_data(convert_rate=SAMPLE_RATE, convert_width=2)
        )
        final_recognition: str = rec.FinalResult()

        result = cast(VoskResponse, json.loads(final_recognition))
        if verbose:
            return result

        return result

    
    @classmethod
    def verify(cls, args):
        path = os.path.join(cls.MODEL_DIR, args["model_name"])
        if not os.path.exists(path):
            return False, f"Vosk model not found at {path}"
        return True, "Vosk model is available."

    @classmethod
    def update(cls, args):
        path = os.path.join(cls.MODEL_DIR, args["model_name"])
        if not os.path.exists(path):
            os.makedirs(path)
        logging.info(f"Downloading Vosk model '{args['model_name']}'")
        download_vosk_model(
            f"https://alphacephei.com/vosk/models/{args['model_name']}.zip",
            path
        ) 