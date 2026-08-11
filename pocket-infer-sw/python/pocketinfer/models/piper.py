from piper import PiperVoice, SynthesisConfig
from piper.download_voices import download_voice
from pocketinfer.audio import AudioPlayer
import threading
import os
import logging
from pathlib import Path
from appdirs import user_cache_dir


class Piper:
    MODEL_DIR = Path(user_cache_dir("pocketinfer")) / "piper_voice"

    def __init__(self, voice_name, audio_device):
        self.logger = logging.getLogger(__name__)
        self.voice_name = voice_name
        self.audio_device = audio_device
        self.voice = PiperVoice.load(model_path=Path(self.MODEL_DIR, voice_name + ".onnx"),
                                     config_path=Path(self.MODEL_DIR, voice_name + ".onnx.json"))
        self.syn_config = SynthesisConfig(
            speaker_id=0,
            length_scale=None,
            noise_scale=None,
            noise_w_scale=None,
            normalize_audio=True,
            volume=1.0,
        )
        self.thread = threading.Thread
        self.playing = False
    
    def _synthesize_and_play(self, text):
        self.logger.debug(f"Starting synthesis and playback on {self.audio_device}")
        with AudioPlayer(self.voice.config.sample_rate, device=self.audio_device) as player:
            for i, audio_chunk in enumerate(self.voice.synthesize(text, self.syn_config)):
                if not self.playing:
                    break
                player.play(audio_chunk.audio_int16_bytes)
        self.logger.debug("Playback complete")

    def start_playback(self, text):
        self.thread = threading.Thread(target=self._synthesize_and_play, args=(text,))
        self.thread.daemon = True
        self.playing = True
        self.thread.start()

    def stop_playback(self):
        if self.playing:
            self.playing = False
            self.thread.join()
    
    @classmethod
    def verify(cls, args):
        if not os.path.exists(cls.MODEL_DIR):
            return False, f"Piper model directory does not exist: {cls.MODEL_DIR}"
        try:
            PiperVoice.load(model_path=Path(cls.MODEL_DIR, args["voice_name"] + ".onnx"),
                            config_path=Path(cls.MODEL_DIR, args["voice_name"] + ".onnx.json"))
            return True, f"Piper voice '{args['voice_name']}' loaded successfully."
        except Exception as e:
            return False, str(e)
        
    @classmethod
    def update(cls, args):
        if not os.path.exists(cls.MODEL_DIR):
            os.makedirs(cls.MODEL_DIR)
        # For Piper, we might download or update the voice model here
        logging.info(f"Downloading Piper voice '{args['voice_name']}'")
        download_voice(args["voice_name"], cls.MODEL_DIR)