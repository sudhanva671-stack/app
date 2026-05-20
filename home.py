"""
Home Automation System — Premium Dark UI + Voice Control
=========================================================
Tested with:
  Python           3.12.3
  SpeechRecognition 3.16.1   (pip install SpeechRecognition==3.16.1)
  pyttsx3          2.99      (pip install pyttsx3==2.99)
  PyAudio          0.2.14    (pip install pyaudio==0.2.14)

Install (all latest):
  pip install SpeechRecognition pyttsx3 pyaudio

Run:
  python app.py

Voice commands (say after clicking the mic button):
  "turn on/off <device>"      e.g. "turn on ceiling light"
  "set brightness to <N>"    e.g. "set brightness to 80"
  "activate scene <name>"    e.g. "activate scene sleep"
  "switch to <room>"         e.g. "switch to bedroom"
  "arm home / arm away / disarm"
  "what's the temperature"
  "list devices"

Compatibility notes (SR 3.16 / pyttsx3 2.99 / PyAudio 0.2.14):
  - sr.Recognizer.recognize_google() still returns a plain str in 3.16.x
  - pyttsx3 2.99 requires one Engine instance per process; we keep a single
    instance and guard runAndWait() with a threading.Lock to prevent re-entry
  - PyAudio 0.2.14 exposes pa.get_default_input_device_info(); we probe this
    before opening the microphone and surface a clear error if no device exists
"""