import base64
import os
import threading

import pyttsx3
import requests
import speech_recognition as sr
from dotenv import load_dotenv


DEEPGRAM_LISTEN_URL = "https://api.deepgram.com/v1/listen"
ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


class VoiceEngine:
    def __init__(self):
        load_dotenv()
        self.recognizer = sr.Recognizer()
        self.engine = None
        self.engine_lock = threading.Lock()
        self.available = True

        try:
            self.engine = pyttsx3.init()
            voices = self.engine.getProperty("voices")
            for voice in voices:
                name = voice.name.lower()
                if "brazil" in name or "portuguese" in name or "portugues" in name:
                    self.engine.setProperty("voice", voice.id)
                    break
            self.engine.setProperty("rate", 180)
        except Exception as e:
            self.available = False
            print(f"Voz TTS indisponivel: {e}")

    def status(self):
        deepgram_configured = bool(os.getenv("DEEPGRAM_API_KEY"))
        elevenlabs_configured = bool(os.getenv("ELEVENLABS_API_KEY"))
        return {
            "local_tts": bool(self.engine),
            "local_stt": True,
            "deepgram_configured": deepgram_configured,
            "deepgram_model": os.getenv("DEEPGRAM_MODEL", "nova-3"),
            "deepgram_language": os.getenv("DEEPGRAM_LANGUAGE", "pt-BR"),
            "elevenlabs_configured": elevenlabs_configured,
            "elevenlabs_voice_id": os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),
            "elevenlabs_model_id": os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2"),
            "stt_provider": "deepgram" if deepgram_configured else "browser/local",
            "tts_provider": "elevenlabs" if elevenlabs_configured else ("pyttsx3" if self.engine else "browser"),
        }

    def transcribe_audio_bytes(self, audio_bytes: bytes, content_type: str = "audio/webm"):
        """Transcreve audio gravado no navegador usando Deepgram."""
        api_key = os.getenv("DEEPGRAM_API_KEY")
        if not api_key:
            return {
                "ok": False,
                "provider": "deepgram",
                "text": "",
                "error": "DEEPGRAM_API_KEY nao configurada.",
            }
        if not audio_bytes:
            return {
                "ok": False,
                "provider": "deepgram",
                "text": "",
                "error": "Audio vazio.",
            }

        params = {
            "model": os.getenv("DEEPGRAM_MODEL", "nova-3"),
            "language": os.getenv("DEEPGRAM_LANGUAGE", "pt-BR"),
            "smart_format": "true",
            "punctuate": "true",
        }
        headers = {
            "Authorization": f"Token {api_key}",
            "Content-Type": content_type or "audio/webm",
        }

        try:
            response = requests.post(
                DEEPGRAM_LISTEN_URL,
                params=params,
                headers=headers,
                data=audio_bytes,
                timeout=45,
            )
        except requests.RequestException as e:
            return {
                "ok": False,
                "provider": "deepgram",
                "text": "",
                "error": f"Falha ao chamar Deepgram: {e}",
            }

        if not response.ok:
            return {
                "ok": False,
                "provider": "deepgram",
                "text": "",
                "status_code": response.status_code,
                "error": response.text[:500],
            }

        payload = response.json()
        alternative = (
            payload.get("results", {})
            .get("channels", [{}])[0]
            .get("alternatives", [{}])[0]
        )
        text = (alternative.get("transcript") or "").strip()
        return {
            "ok": bool(text),
            "provider": "deepgram",
            "text": text,
            "confidence": alternative.get("confidence"),
            "duration": payload.get("metadata", {}).get("duration"),
        }

    def generate_speech_audio(self, text: str):
        """Gera audio TTS em base64 usando ElevenLabs para reproducao no navegador."""
        api_key = os.getenv("ELEVENLABS_API_KEY")
        if not api_key:
            return {
                "ok": False,
                "provider": "elevenlabs",
                "error": "ELEVENLABS_API_KEY nao configurada.",
            }
        text = (text or "").strip()
        if not text:
            return {
                "ok": False,
                "provider": "elevenlabs",
                "error": "Texto vazio.",
            }

        voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
        model_id = os.getenv("ELEVENLABS_MODEL_ID", "eleven_multilingual_v2")
        url = ELEVENLABS_TTS_URL.format(voice_id=voice_id)
        params = {"output_format": os.getenv("ELEVENLABS_OUTPUT_FORMAT", "mp3_44100_128")}
        body = {
            "text": text[:2500],
            "model_id": model_id,
            "voice_settings": {
                "stability": _env_float("ELEVENLABS_STABILITY", 0.45),
                "similarity_boost": _env_float("ELEVENLABS_SIMILARITY", 0.75),
                "style": _env_float("ELEVENLABS_STYLE", 0.0),
                "use_speaker_boost": os.getenv("ELEVENLABS_SPEAKER_BOOST", "1") != "0",
            },
        }
        headers = {
            "xi-api-key": api_key,
            "Accept": "audio/mpeg",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(url, params=params, headers=headers, json=body, timeout=45)
        except requests.RequestException as e:
            return {
                "ok": False,
                "provider": "elevenlabs",
                "error": f"Falha ao chamar ElevenLabs: {e}",
            }

        if not response.ok:
            return {
                "ok": False,
                "provider": "elevenlabs",
                "status_code": response.status_code,
                "error": response.text[:500],
            }

        return {
            "ok": True,
            "provider": "elevenlabs",
            "mime_type": "audio/mpeg",
            "audio_base64": base64.b64encode(response.content).decode("ascii"),
            "voice_id": voice_id,
            "model_id": model_id,
        }

    def list_microphones(self):
        try:
            return sr.Microphone.list_microphone_names()
        except Exception as e:
            return [f"Erro ao listar microfones: {e}"]

    def _device_index(self):
        raw_value = os.getenv("ELITE_MIC_DEVICE_INDEX")
        if raw_value not in (None, ""):
            try:
                return int(raw_value)
            except ValueError:
                return None

        names = self.list_microphones()
        if not names or names[0].startswith("Erro ao listar microfones"):
            return None
        preferred_terms = ("microfone", "frontmic", "mic input", "headset")
        for index, name in enumerate(names):
            normalized = name.lower()
            if any(term in normalized for term in preferred_terms):
                return index
        return None

    def speak(self, text: str):
        """Fala um texto em background sem bloquear a interface."""
        if not self.engine or not text:
            return

        def _speak():
            try:
                with self.engine_lock:
                    self.engine.say(text)
                    self.engine.runAndWait()
            except Exception as e:
                print(f"Erro na fala: {e}")

        threading.Thread(target=_speak, daemon=True).start()

    def listen(self) -> str:
        """Escuta o microfone e retorna o texto reconhecido."""
        microphones = self.list_microphones()
        if not microphones:
            return "Microfone indisponivel: nenhum dispositivo de entrada foi encontrado."
        if microphones and microphones[0].startswith("Erro ao listar microfones"):
            return f"Microfone indisponivel: {microphones[0]}"

        try:
            with sr.Microphone(device_index=self._device_index()) as source:
                print("Ouvindo...")
                self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                audio = self.recognizer.listen(source, timeout=6, phrase_time_limit=12)
        except Exception as e:
            return f"Microfone indisponivel: {str(e)}"

        try:
            text = self.recognizer.recognize_google(audio, language="pt-BR")
            print(f"Voce disse: {text}")
            return text
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            return f"Erro no servico de reconhecimento: {str(e)}"

    def start_wake_word_detection(self, callback):
        """Monitora o microfone em segundo plano procurando pela palavra-chave 'Elite'."""
        def _background_listener():
            print("Detector de palavra-chave 'Elite' ativado.")
            while True:
                try:
                    with sr.Microphone(device_index=self._device_index()) as source:
                        self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                        audio = self.recognizer.listen(source, timeout=8, phrase_time_limit=5)
                    text = self.recognizer.recognize_google(audio, language="pt-BR").lower()
                    if "elite" in text:
                        print("Palavra-chave detectada.")
                        self.speak("Sim?")
                        command = self.listen()
                        if command and not command.startswith("Microfone indisponivel"):
                            callback(command)
                except sr.WaitTimeoutError:
                    continue
                except Exception as e:
                    print(f"Detector de voz pausado por erro: {e}")
                    break

        threading.Thread(target=_background_listener, daemon=True).start()


voice = VoiceEngine()
