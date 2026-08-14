from pocketinfer.applications.base import BaseApplication
from pocketinfer.applications.registry import RegisterApplication

from pocketinfer.models.ollama import Ollama
from pocketinfer.models.piper import Piper
from pocketinfer.models.vosk import Vosk

import time
import os
import json


# Register this class as an application that can run on the Pocket Infer Device
# The argument here is a dictionary of metadata about the application
# Metadata will be used to instantiate the application and ensure dependencies are met
@RegisterApplication({
    "name": "Hear The World (English)",
    "description": "An application that allows the user to ask questions in english about their surroundings.",
    "author": "PocketInfer",
    "version": "0.1.0",
    "models": {
        "ollama": {"model_name": "qwen3-vl:2b"},
        # "ollama": {"model_name": "moondream:1.8B"},
        # "ollama": {"model_name": "ministral-3:3B"},
        "piper": {"voice_name": "en_US-lessac-medium"},
        "vosk": {"model_name": "vosk-model-small-en-us-0.15"},
    },
    "service_dependencies": ["ollama"],
})
class HearTheWorldEn(BaseApplication):
    def start(self):
        # Load any models or resources needed for the application
        self.piper = Piper(voice_name=self.METADATA["models"]["piper"]["voice_name"],
                           audio_device=self.board.alsa_playback_device)
        self.vosk = Vosk(model_name=self.METADATA["models"]["vosk"]["model_name"])
        self.ollama = Ollama(model_name=self.METADATA["models"]["ollama"]["model_name"])
        # Proceed with running the application in it's own thread
        if not os.path.exists("/tmp/hear_the_world_en_logs"):
            os.makedirs("/tmp/hear_the_world_en_logs")
        super().start()

    def run(self):
        self.board.clear_screen()
        while self.running:
            self.board.statusbar("Ready - Press Button")
            self.board.wait_for_trigger_button_down()
            self.board.statusbar("Release Button")
            self.board.top_text("")
            self.board.bottom_text("")
            audio_start = time.time()
            # When user presses button, start recording audio and snap a photo
            self.piper.stop_playback()  # If previous TTS is still playing, stop it
            self.board.audio.start()
            img = self.board.camera_frame_jpg()
            self.board.wait_for_trigger_button_up()
            audio_stop = time.time()
            # When user releases button, stop recording
            self.board.audio.stop()
            self.board.statusbar("Running: ASR")
            asr_start = time.time()
            # Perform ASR on the recorded audio, convert it to text
            asr_result = self.vosk.recognize(self.board.audio.to_audio_data())
            query = asr_result['text']
            asr_stop = time.time()
            self.logger.info("Detected query is '{}'".format(query))
            self.board.top_text(query)
            # Perform LLM inference on the recognized text + image
            self.board.statusbar("Running: LLM")
            llm_start = time.time()
            resp = self.ollama.generate(images=[img], prompt=query+'. Limit response to one short sentence')
            llm_end = time.time()
            result = resp.response.strip().rstrip()
            self.logger.info("Result is '{}'".format(result))
            self.board.bottom_text(result)
            # Perform TTS on the LLM response, convert it to audio and play it back
            self.board.statusbar("Running: Playback")
            if '.' in result:
                result = result.split('.')[0]
            self.piper.start_playback(result)
            app_end = time.time()
            self.logger.debug(f"Total Run time {app_end-audio_start}s, audio {audio_stop-audio_start}s, ASR {asr_stop-asr_start}, LLM {llm_end-llm_start}")
            # Log
            log_id = int(audio_start*1000)
            log_data = {
                'id': log_id,
                "query": asr_result,
                "response": resp.model_dump(),
                "timestamps": {
                    "audio_start": audio_start,
                    "audio_stop": audio_stop,
                    "asr_start": asr_start,
                    "asr_stop": asr_stop,
                    "llm_start": llm_start,
                    "llm_end": llm_end,
                    "app_end": app_end
                }
            }
            with open("/tmp/hear_the_world_en_logs/log.jsonl", "a") as f:
                f.write(json.dumps(log_data)+"\n")
            with open("/tmp/hear_the_world_en_logs/img_{}.jpg".format(log_id), "wb") as f:
                f.write(img)
            self.board.audio.save_to_file("/tmp/hear_the_world_en_logs/audio_{}.wav".format(log_id))
            # Loop back around and prepare for the next interactionw
