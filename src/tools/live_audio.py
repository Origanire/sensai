"""Ce module transcrit le son du live sans conserver d’enregistrement. Il ne reconnaît pas les personnes et n’exécute pas de commandes vocales."""
import importlib.util
import json
import queue
import re
import signal
import subprocess
import sys
import threading
import time


def dependencies_ready():
    return all(importlib.util.find_spec(name) is not None for name in
               ('streamlink', 'faster_whisper', 'imageio_ffmpeg'))


def voice_request(text, wake_word='Lumi'):
    # On attend le mot d’appel pour répondre. On accepte aussi les transcriptions « Lumie » et « Loumi ».
    pattern = r'(?:Lumie?|Loumi)' if wake_word.casefold() == 'lumi' else re.escape(wake_word)
    match = re.search(r'(?<!\w)' + pattern + r'(?!\w)', text, re.I)
    if not match:
        return None
    request = text[match.end():].lstrip(' ,:;').rstrip(' ,:;?.…')
    return request if request.strip('! ') else ''


def put_latest(target, item):
    try:
        target.put_nowait(item)
    except queue.Full:
        try:
            target.get_nowait()
        except queue.Empty:
            pass
        target.put_nowait(item)


class LiveAudio:
    """Cette classe gère l’écoute depuis la boucle du chat et limite les transcriptions en attente."""
    def __init__(self, channel, emit):
        self.channel, self.emit = channel, emit
        self.process = None
        self.inbox = queue.Queue(maxsize=4)
        self.retry_at = 0

    def update(self, enabled):
        if not enabled:
            self.stop()
            return
        if self.process and self.process.poll() is None:
            return
        if time.monotonic() < self.retry_at:
            return
        self.retry_at = time.monotonic() + 60
        if not dependencies_ready():
            self.emit('audio', stage='missing')
            return
        self.emit('audio', stage='starting')
        self.process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'src.tools.live_audio', self.channel],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
            start_new_session=True,
        )
        process = self.process
        def read():
            for line in process.stdout:
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        put_latest(self.inbox, (process, item))
                except ValueError:
                    continue
            process.stdout.close()
        threading.Thread(target=read, daemon=True).start()

    def poll(self):
        while True:
            try:
                process, item = self.inbox.get_nowait()
            except queue.Empty:
                return None
            if process is not self.process:
                continue
            if item.get('stage'):
                self.emit('audio', stage=item['stage'])
            text = item.get('text')
            if isinstance(text, str) and 0 <= time.time() - item.get('at', 0) < 45:
                return text[:500]

    def stop(self):
        process, self.process = self.process, None
        if process:
            import os
            # On arrête la capture et le décodage ensemble pour ne pas laisser l’écoute tourner seule.
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            self.emit('audio', stage='stopped')
        self.retry_at = 0


def worker(channel):
    if not re.fullmatch(r'[a-zA-Z0-9_]{3,25}', channel):
        raise ValueError('Invalid channel')
    import numpy as np
    from faster_whisper import WhisperModel
    from imageio_ffmpeg import get_ffmpeg_exe

    def report(**data):
        print(json.dumps(data, ensure_ascii=False), flush=True)

    capture = decoder = None
    def terminate(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    try:
        report(stage='loading')
        model = WhisperModel('small', device='cpu', compute_type='int8', cpu_threads=4)
        capture = subprocess.Popen([
            sys.executable, '-m', 'streamlink', '--loglevel', 'none', '--stdout',
            '--stream-timeout', '20', '--hls-live-edge', '2',
            'https://www.twitch.tv/' + channel, 'audio_only,worst',
        ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        decoder = subprocess.Popen([
            get_ffmpeg_exe(), '-loglevel', 'error', '-i', 'pipe:0', '-vn',
            '-f', 's16le', '-acodec', 'pcm_s16le', '-ac', '1', '-ar', '16000', 'pipe:1',
        ], stdin=capture.stdout, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        capture.stdout.close()
        chunks = queue.Queue(maxsize=2)
        def read_audio():
            while True:
                block = decoder.stdout.read(16000 * 2 * 12)
                if len(block) < 16000 * 2:
                    put_latest(chunks, None)
                    return
                put_latest(chunks, (time.time(), block))
        threading.Thread(target=read_audio, daemon=True).start()
        previous = ''
        while True:
            try:
                chunk = chunks.get(timeout=40)
            except queue.Empty:
                report(stage='unavailable')
                return
            if chunk is None:
                report(stage='unavailable')
                return
            report(stage='listening')
            captured_at, pcm = chunk
            waveform = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(waveform, language='fr', beam_size=1,
                                          vad_filter=True, condition_on_previous_text=False)
            text = ' '.join(s.text.strip() for s in segments
                            if s.no_speech_prob < .6 and s.avg_logprob > -1).strip()
            if text and text != previous and time.time() - captured_at < 45:
                previous = text
                report(text=text, at=captured_at)
    except Exception:
        report(stage='unavailable')
    finally:
        for process in (decoder, capture):
            if process:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == '__main__':
    worker(sys.argv[1])
