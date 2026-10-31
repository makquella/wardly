# Word timings of the voice takes (faster-whisper "medium", CPU): python tools/transcribe_vo.py audio/vo/words.json audio/vo/vo?.wav
import sys, json
from faster_whisper import WhisperModel
m = WhisperModel("medium", device="cpu", compute_type="int8")
out = {}
for f in sys.argv[2:]:
    segs, info = m.transcribe(f, language="uk", word_timestamps=True, beam_size=5)
    out[f.split('/')[-1]] = {"duration": info.duration, "words": [{"w": w.word.strip(), "s": round(w.start,3), "e": round(w.end,3), "p": round(w.probability,2)} for s in segs for w in s.words]}
json.dump(out, open(sys.argv[1], "w"), ensure_ascii=False, indent=1)
