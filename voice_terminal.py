#!/usr/bin/env python3
"""
Voice Terminal - A macOS menubar app for voice-to-text in any application.

Mode 1: Press Cmd+Shift+Z to transcribe speech directly.
Mode 2: Press Cmd+Shift+A to send clipboard + speech to Claude, paste response.
"""

import io
import os
import subprocess
import tempfile
import threading
import wave

import numpy as np
import rumps
import sounddevice as sd
from dotenv import load_dotenv
from openai import OpenAI
from pynput import keyboard


def play_sound(sound_name):
    """Play a macOS system sound."""
    sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
    subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def get_clipboard():
    """Read current clipboard contents."""
    result = subprocess.run(['pbpaste'], capture_output=True, text=True)
    return result.stdout


def set_clipboard_and_paste(text):
    """Copy text to clipboard and paste it."""
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
    subprocess.run([
        'osascript', '-e',
        'tell application "System Events" to keystroke "v" using command down'
    ], check=True)


# Load environment variables from .env file
load_dotenv()

# Configuration
HOTKEY_TRANSCRIBE = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char('z')}
HOTKEY_CLAUDE = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char('a')}
SAMPLE_RATE = 16000  # Whisper expects 16kHz
CHANNELS = 1


class VoiceTerminalApp(rumps.App):
    def __init__(self):
        super().__init__("Voice Terminal", icon=None, title="🎤")

        # State
        self.recording = False
        self.audio_data = []
        self.current_keys = set()
        self.stream = None
        self.current_mode = None  # 'transcribe' or 'claude'
        self.clipboard_context = None  # Stored clipboard for claude mode

        # OpenAI client (for Whisper)
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            rumps.alert(
                title="API Key Missing",
                message="Please set OPENAI_API_KEY environment variable.\n\n"
                        "export OPENAI_API_KEY='your-key-here'"
            )
        self.whisper_client = OpenAI(api_key=api_key) if api_key else None

        # LLM client (for Claude mode)
        llm_api_key = os.environ.get("LLM_API_KEY")
        llm_base_url = os.environ.get("LLM_BASE_URL")
        self.llm_model = os.environ.get("LLM_MODEL", "claude-opus-4-5-20250514")

        if llm_api_key and llm_base_url and llm_api_key != "your-llm-api-key-here":
            self.llm_client = OpenAI(api_key=llm_api_key, base_url=llm_base_url)
        else:
            self.llm_client = None

        # Menu items
        self.menu = [
            rumps.MenuItem("Status: Ready", callback=None),
            None,  # Separator
            rumps.MenuItem("Cmd+Shift+Z: Transcribe", callback=None),
            rumps.MenuItem("Cmd+Shift+A: Ask Claude", callback=None),
            None,
        ]

        # Start hotkey listener
        self.listener = keyboard.Listener(
            on_press=self.on_key_press,
            on_release=self.on_key_release
        )
        self.listener.start()

    def on_key_press(self, key):
        """Handle key press events."""
        self.current_keys.add(key)

        # Check which hotkey combination is pressed
        if not self.recording:
            if self.check_hotkey(HOTKEY_TRANSCRIBE):
                self.current_mode = 'transcribe'
                self.start_recording()
            elif self.check_hotkey(HOTKEY_CLAUDE):
                self.current_mode = 'claude'
                # Capture clipboard before recording
                self.clipboard_context = get_clipboard()
                self.start_recording()

    def on_key_release(self, key):
        """Handle key release events."""
        # If any hotkey key is released while recording, stop
        if self.recording:
            if key in HOTKEY_TRANSCRIBE or key in HOTKEY_CLAUDE:
                self.stop_recording()

        # Remove key from current set
        self.current_keys.discard(key)

    def check_hotkey(self, hotkey):
        """Check if a specific hotkey combination is currently pressed."""
        # Normalize keys for comparison
        normalized_current = set()
        for k in self.current_keys:
            if isinstance(k, keyboard.KeyCode) and k.char:
                normalized_current.add(keyboard.KeyCode.from_char(k.char.lower()))
            else:
                normalized_current.add(k)

        return hotkey.issubset(normalized_current)

    def start_recording(self):
        """Start recording audio."""
        if not self.whisper_client:
            rumps.notification(
                title="Voice Terminal",
                subtitle="Error",
                message="OpenAI API key not configured"
            )
            return

        if self.current_mode == 'claude' and not self.llm_client:
            rumps.notification(
                title="Voice Terminal",
                subtitle="Error",
                message="LLM API not configured. Set LLM_API_KEY and LLM_BASE_URL in .env"
            )
            return

        self.recording = True
        self.audio_data = []

        # Different visual feedback per mode
        if self.current_mode == 'transcribe':
            self.title = "🔴"
            self.menu["Status: Ready"].title = "Status: Recording..."
        else:  # claude mode
            self.title = "🟣"
            self.menu["Status: Ready"].title = "Status: Recording (Claude)..."

        # Start audio stream
        def audio_callback(indata, frames, time, status):
            if self.recording:
                self.audio_data.append(indata.copy())

        self.stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype=np.float32,
            callback=audio_callback
        )
        self.stream.start()

        # Audio feedback - recording started
        play_sound("Tink")

        if self.current_mode == 'transcribe':
            rumps.notification(
                title="Voice Terminal",
                subtitle="Recording",
                message="Speak now... Release hotkey when done."
            )
        else:
            context_preview = self.clipboard_context[:30] + "..." if len(self.clipboard_context) > 30 else self.clipboard_context
            rumps.notification(
                title="Voice Terminal",
                subtitle="Recording (Claude Mode)",
                message=f"Context: {context_preview or '(empty)'}"
            )

    def stop_recording(self):
        """Stop recording and process audio."""
        if not self.recording:
            return

        self.recording = False

        # Different visual feedback per mode
        if self.current_mode == 'transcribe':
            self.title = "⏳"
            self.menu["Status: Ready"].title = "Status: Transcribing..."
        else:
            self.title = "🤖"
            self.menu["Status: Ready"].title = "Status: Asking Claude..."

        # Audio feedback - recording stopped
        play_sound("Pop")

        # Stop audio stream
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None

        # Process in background thread to not block UI
        threading.Thread(target=self.process_audio, daemon=True).start()

    def process_audio(self):
        """Process recorded audio: transcribe and optionally send to Claude."""
        try:
            if not self.audio_data:
                self.reset_status()
                return

            # Combine audio chunks
            audio = np.concatenate(self.audio_data, axis=0)

            # Convert to WAV format for Whisper API
            wav_buffer = io.BytesIO()
            with wave.open(wav_buffer, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(2)  # 16-bit
                wav_file.setframerate(SAMPLE_RATE)
                # Convert float32 to int16
                audio_int16 = (audio * 32767).astype(np.int16)
                wav_file.writeframes(audio_int16.tobytes())

            wav_buffer.seek(0)

            # Create a temporary file for the API
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp.write(wav_buffer.read())
                tmp_path = tmp.name

            try:
                # Transcribe with Whisper
                with open(tmp_path, "rb") as audio_file:
                    transcript = self.whisper_client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="text"
                    )

                text = transcript.strip()

                if text:
                    if self.current_mode == 'transcribe':
                        # Mode 1: Direct transcription
                        set_clipboard_and_paste(text)
                        rumps.notification(
                            title="Voice Terminal",
                            subtitle="Typed",
                            message=text[:50] + "..." if len(text) > 50 else text
                        )
                    else:
                        # Mode 2: Send to Claude
                        response = self.call_llm(self.clipboard_context, text)
                        set_clipboard_and_paste(response)
                        rumps.notification(
                            title="Voice Terminal",
                            subtitle="Claude Response",
                            message=response[:50] + "..." if len(response) > 50 else response
                        )
                else:
                    rumps.notification(
                        title="Voice Terminal",
                        subtitle="No Speech",
                        message="No speech detected"
                    )
            finally:
                # Clean up temp file
                os.unlink(tmp_path)

        except Exception as e:
            rumps.notification(
                title="Voice Terminal",
                subtitle="Error",
                message=str(e)[:100]
            )

        finally:
            self.reset_status()

    def call_llm(self, context: str, prompt: str) -> str:
        """Send context + prompt to Claude and return response."""
        if context:
            user_message = f"Context:\n```\n{context}\n```\n\nRequest: {prompt}"
        else:
            user_message = prompt

        response = self.llm_client.chat.completions.create(
            model=self.llm_model,
            max_tokens=4096,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant. The user may provide context (code, text, etc.) along with a spoken request. Respond concisely and directly - your response will be pasted into their editor or terminal."
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )
        return response.choices[0].message.content

    def reset_status(self):
        """Reset app status to ready state."""
        self.title = "🎤"
        self.menu["Status: Ready"].title = "Status: Ready"
        self.audio_data = []
        self.current_mode = None
        self.clipboard_context = None


if __name__ == "__main__":
    VoiceTerminalApp().run()
