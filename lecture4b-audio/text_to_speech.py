import argparse
import tempfile
from contextlib import suppress
from pathlib import Path

from openai import OpenAI

from speech import _write_speech_audio, TTS_MODEL, TTS_SPEED, TTS_VOICE
from usage import print_usage

DEFAULT_TEXT = 'Hello from the text to speech demo.'
DEFAULT_INSTRUCTIONS = 'Speak in a clear, conversational, friendly tone.'

client = OpenAI()


def load_text(text: str | None, text_file: Path | None) -> str:
    """Resolve the text to speak from a literal string or a file."""
    if text_file:
        return text_file.read_text().strip()
    if text:
        return text.strip()
    return ''


def generate_speech(text: str, instructions: str, voice: str, usages: list[tuple[str, object]]) -> Path:
    """Generate speech audio from input text and return the temporary WAV path."""
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
        audio_path = Path(handle.name)

    response = client.audio.speech.create(
        model=TTS_MODEL,
        voice=voice,
        input=text,
        instructions=instructions,
        response_format='wav',
        speed=TTS_SPEED,
    )

    usage = getattr(response, 'usage', None)
    if usage is not None:
        usages.append((TTS_MODEL, usage))

    _write_speech_audio(response, audio_path)
    return audio_path


def play_audio(audio_path: Path) -> None:
    """Play a local WAV file through the system audio output."""
    import subprocess

    subprocess.run(
        ['/usr/bin/afplay', str(audio_path)],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main(text: str | None, text_file: Path | None, instructions: str, voice: str) -> None:
    usages: list[tuple[str, object]] = []

    print('Text To Speech Demo')
    print('Enter text and the program will generate spoken audio.')

    current_text = load_text(text, text_file)
    if current_text:
        print('\nStarting text:')
        print(current_text)

    while True:
        if not current_text:
            current_text = input('\nText to speak: ').strip()
        if not current_text:
            print('Please enter some text.')
            continue

        audio_path = generate_speech(current_text, instructions, voice, usages)
        try:
            play_audio(audio_path)
        finally:
            with suppress(FileNotFoundError):
                audio_path.unlink()

        again = input('\nPress Enter to try again, or type q to quit: ').strip().lower()
        if again in {'q', 'quit'}:
            break
        current_text = ''

    if usages:
        print()
        print_usage(usages)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('TextToSpeechDemo')
    parser.add_argument('--text', default=DEFAULT_TEXT)
    parser.add_argument('--text-file', type=Path, default=None)
    parser.add_argument('--instructions', default=DEFAULT_INSTRUCTIONS)
    parser.add_argument(
        '--voice',
        default=TTS_VOICE,
        choices=['alloy', 'ash', 'ballad', 'coral', 'echo', 'sage', 'shimmer', 'verse', 'marin', 'cedar'],
    )
    args = parser.parse_args()
    main(args.text, args.text_file, args.instructions, args.voice)
