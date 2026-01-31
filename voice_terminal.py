#!/usr/bin/env python3
"""
Voice Terminal - A macOS menubar app for voice-to-text in any application.

Press Cmd+Shift+V to start recording, release to transcribe and type.
"""

import io
import os
import subprocess
import tempfile
import threading
import wave

import numpy as np
import pyautogui
import rumps
import sounddevice as sd
from dotenv import load_dotenv
from openai import OpenAI
from pynput import keyboard


def play_sound(sound_name):
    """Play a macOS system sound."""
    sound_path = f"/System/Library/Sounds/{sound_name}.aiff"
    subprocess.Popen(["afplay", sound_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

# Load environment variables from .env file
load_dotenv()

# Configuration
HOTKEY = {keyboard.Key.cmd, keyboard.Key.shift, keyboard.KeyCode.from_char('z')}
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

        # OpenAI client
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            rumps.alert(
                title="API Key Missing",
                message="Please set OPENAI_API_KEY environment variable.\n\n"
                        "export OPENAI_API_KEY='your-key-here'"
            )
        self.client = OpenAI(api_key=api_key) if api_key else None

        # Menu items
        self.menu = [
            rumps.MenuItem("Status: Ready", callback=None),
            None,  # Separator
            rumps.MenuItem("Hotkey: Cmd+Shift+Z", callback=None),
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

        # Check if hotkey combination is pressed
        if self.check_hotkey() and not self.recording:
            self.start_recording()

    def on_key_release(self, key):
        """Handle key release events."""
        # If any hotkey key is released while recording, stop
        if self.recording and key in HOTKEY:
            self.stop_recording()

        # Remove key from current set
        self.current_keys.discard(key)

    def check_hotkey(self):
        """Check if the hotkey combination is currently pressed."""
        # Normalize keys for comparison
        normalized_current = set()
        for k in self.current_keys:
            if isinstance(k, keyboard.KeyCode) and k.char:
                normalized_current.add(keyboard.KeyCode.from_char(k.char.lower()))
            else:
                normalized_current.add(k)

        return HOTKEY.issubset(normalized_current)

    def start_recording(self):
        """Start recording audio."""
        if not self.client:
            rumps.notification(
                title="Voice Terminal",
                subtitle="Error",
                message="OpenAI API key not configured"
            )
            return

        self.recording = True
        self.audio_data = []
        self.title = "🔴"  # Red circle indicates recording
        self.menu["Status: Ready"].title = "Status: Recording..."

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

        rumps.notification(
            title="Voice Terminal",
            subtitle="Recording",
            message="Speak now... Release hotkey when done."
        )

    def stop_recording(self):
        """Stop recording and process audio."""
        if not self.recording:
            return

        self.recording = False
        self.title = "⏳"  # Hourglass indicates processing
        self.menu["Status: Ready"].title = "Status: Transcribing..."

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
        """Process recorded audio: transcribe and type."""
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
                    transcript = self.client.audio.transcriptions.create(
                        model="whisper-1",
                        file=audio_file,
                        response_format="text"
                    )

                text = transcript.strip()

                if text:
                    # Copy to clipboard and paste (instant vs character-by-character)
                    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
                    # Use AppleScript for reliable Cmd+V on macOS
                    subprocess.run([
                        'osascript', '-e',
                        'tell application "System Events" to keystroke "v" using command down'
                    ], check=True)

                    rumps.notification(
                        title="Voice Terminal",
                        subtitle="Typed",
                        message=text[:50] + "..." if len(text) > 50 else text
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

    def reset_status(self):
        """Reset app status to ready state."""
        self.title = "🎤"
        self.menu["Status: Ready"].title = "Status: Ready"
        self.audio_data = []


if __name__ == "__main__":
    VoiceTerminalApp().run()
