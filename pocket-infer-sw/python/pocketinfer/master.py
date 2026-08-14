import sys
import os
import time
import argparse
import logging
import threading
import subprocess
import requests
from pocketinfer.service import main as service_main
from pocketinfer.applications.registry import ApplicationRegistry


def check_and_start_service(service_name: str) -> bool:
    """Check systemd service status and start if inactive."""
    try:
        res = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
        if res.stdout.strip() == "active":
            logging.info(f"Service '{service_name}' is active.")
            return True
        logging.warning(f"Service '{service_name}' is inactive ({res.stdout.strip()}). Attempting start...")
        subprocess.run(["systemctl", "start", service_name], check=False)
        time.sleep(2)
        res_after = subprocess.run(["systemctl", "is-active", service_name], capture_output=True, text=True)
        return res_after.stdout.strip() == "active"
    except Exception as e:
        logging.error(f"Error checking service '{service_name}': {e}")
        return False


def app_needs_ollama(app_name: str) -> bool:
    """
    Returns True if the target application declares an 'ollama' model dependency
    in its @RegisterApplication METADATA. Apps that never call Ollama (e.g.
    NomadRight, which is BHASHINI-only) don't need it started or pre-warmed -
    doing so anyway wastes ~2.4GB of RAM held forever (keep_alive=-1) and has
    been observed to starve other processes on this 8GB device.
    """
    app_cls = ApplicationRegistry.get_application(app_name)
    if app_cls is None:
        # Unknown app name - be conservative and pre-warm anyway.
        return True
    return "ollama" in app_cls.METADATA.get("models", {})


def verify_ollama_model(model_name: str = "qwen3-vl:2b") -> bool:
    """Verify Ollama is reachable and asynchronously pre-warm model into RAM with keep_alive=-1."""
    logging.info(f"Verifying Ollama endpoint and pre-warming model '{model_name}'...")
    try:
        resp = requests.get("http://localhost:11434/api/tags", timeout=5.0)
        if resp.status_code != 200:
            logging.error("Ollama API is not responding properly.")
            return False
        models = [m.get("name") for m in resp.json().get("models", [])]
        logging.info(f"Ollama available models: {models}")

        def _async_warmup():
            try:
                requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": model_name,
                        "prompt": "",
                        "keep_alive": -1,
                        "options": {"num_thread": 6}
                    },
                    timeout=60.0
                )
                logging.info(f"Model '{model_name}' pre-warmed into RAM.")
            except Exception as e:
                logging.warning(f"Async model warmup notice: {e}")

        threading.Thread(target=_async_warmup, daemon=True).start()
        return True
    except Exception as e:
        logging.error(f"Ollama verification failed: {e}")
        return False


def verify_bhashini_service() -> bool:
    """Verify Bhashini Models (ASR, NMT, TTS) health."""
    logging.info("Verifying Bhashini Models service (http://localhost:11400/health)...")
    try:
        resp = requests.get("http://localhost:11400/health", timeout=5.0)
        if resp.status_code == 200:
            logging.info("Bhashini Models service is healthy.")
            return True
    except Exception as e:
        logging.warning(f"Bhashini health check failed: {e}")
    return False


def clean_system_caches():
    """Drop Linux caches to free RAM for inference."""
    try:
        if os.geteuid() == 0:
            subprocess.run("sync && echo 3 > /proc/sys/vm/drop_caches", shell=True, check=False)
            logging.info("Cleared system RAM caches.")
        else:
            logging.debug("Non-root execution: skipping drop_caches write.")
    except Exception:
        pass


def stop_conflicting_instances():
    """Stop active systemd pocketinfer.service if running interactively to avoid hardware locks."""
    try:
        res = subprocess.run(["systemctl", "is-active", "pocketinfer.service"], capture_output=True, text=True)
        if res.stdout.strip() == "active":
            logging.info("Stopping active background 'pocketinfer.service' to release hardware locks...")
            subprocess.run(["systemctl", "stop", "pocketinfer.service"], check=False)
            time.sleep(1.0)
    except Exception:
        pass


def run_master():
    parser = argparse.ArgumentParser(description="PocketInfer Master Setup Command")
    parser.add_argument('--app', type=str, default="HearTheWorld", help="Application to launch")
    parser.add_argument('--model', type=str, default="qwen3-vl:2b", help="Ollama model name")
    parser.add_argument('--status', action='store_true', help="Check services and exit")
    parser.add_argument('--dummy-board', action='store_true', help="Run in dummy hardware mode")
    parser.add_argument('--log-level', type=str, default="INFO", help="Logging level")
    args, unknown = parser.parse_known_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    )

    print("=" * 60)
    print("      PocketInfer Master Command - Jetson Orion Nano       ")
    print("=" * 60)

    needs_ollama = app_needs_ollama(args.app)

    # 1. Service checks
    if needs_ollama:
        ollama_ok = check_and_start_service("ollama.service")
    else:
        logging.info(f"App '{args.app}' does not use Ollama - skipping ollama.service start.")
        ollama_ok = True
    bhashini_ok = check_and_start_service("bhashini_models.service")

    # 2. Warm up models
    if needs_ollama:
        verify_ollama_model(args.model)
    else:
        logging.info(f"App '{args.app}' does not use Ollama - skipping model pre-warm (saves ~2.4GB RAM).")
    verify_bhashini_service()

    if args.status:
        print("\n--- System Status Summary ---")
        print(f"Ollama Service:   {'[OK]' if ollama_ok else '[FAILED]'}{'  (skipped - not needed by this app)' if not needs_ollama else ''}")
        print(f"Bhashini Models:  {'[OK]' if bhashini_ok else '[FAILED]'}")
        sys.exit(0)

    # 3. Handle process conflicts
    stop_conflicting_instances()

    # 4. Clean caches
    clean_system_caches()
    time.sleep(0.5)

    # 5. Launch PocketInfer service
    logging.info(f"Starting PocketInfer Application: {args.app}")
    extra_flags = []
    if args.dummy_board and '--dummy-board' not in unknown:
        extra_flags.append('--dummy-board')
    sys.argv = [sys.argv[0], "--app", args.app, "--log-level", args.log_level] + extra_flags + unknown
    service_main()


if __name__ == "__main__":
    run_master()
