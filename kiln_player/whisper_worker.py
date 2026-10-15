"""Run pywhispercpp on a 16 kHz mono WAV and print one JSON line per segment.

Started by whisper.py as a separate process so a transcription can be
cancelled at any moment and a crash in native code cannot take the player down.
"""

import argparse
import json
import sys
import wave


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--wav", required=True)
    ap.add_argument("--language", default="auto")
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--translate", action="store_true")
    args = ap.parse_args()

    import numpy as np
    from pywhispercpp.model import Model

    with wave.open(args.wav, "rb") as wf:
        if wf.getframerate() != 16000 or wf.getnchannels() != 1 or wf.getsampwidth() != 2:
            sys.exit("audio must be 16 kHz mono 16-bit")
        audio = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0

    def emit(seg):
        # pywhispercpp reports times in units of 10 ms.
        print(json.dumps({"seg": [seg.t0 / 100, seg.t1 / 100, seg.text]}), flush=True)

    model = Model(args.model, redirect_whispercpp_logs_to=None, n_threads=args.threads,
                  print_progress=False, print_realtime=False)
    model.transcribe(audio, language="" if args.language == "auto" else args.language,
                     translate=args.translate, new_segment_callback=emit)


if __name__ == "__main__":
    main()
