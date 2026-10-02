#!/usr/bin/env python3
"""녹음 끝 잘림 검사 — language-teacher/audio/{언어}/*.mp3

Chirp 3 HD는 가끔 말하는 도중에 소리를 끊어서 돌려줘요(특히 "no", "hola" 같은 한 단어, "¿Y tú?"로 끝나는 짧은 문장).
끊긴 파일은 마지막 30ms에도 소리가 커요. 자연스럽게 끝난 파일은 마지막 30ms가 -45dB보다 조용해요.

  python3 tools/tts/check.py                 # 검사만(언어별 개수 + 의심 파일 목록)
  python3 tools/tts/check.py --lang es,en    # 고른 언어만
  python3 tools/tts/check.py --delete        # 의심 파일을 지워요 → generate.mjs를 다시 돌리면 그 파일만 새로 녹음

필요한 것: ffmpeg(시스템에 있으면 그것, 없으면 `pip install imageio-ffmpeg`).
지운 뒤 다시 녹음하는 것은 목소리·속도가 같아서 index.json의 rev는 그대로예요. 이미 배포된 파일을 고친다면
index.json의 gen을 1 올리고 `node tools/tts/generate.mjs --lang xx --limit 0`으로 rev를 다시 계산하세요(README 참고).
"""
import argparse
import array
import math
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
AUDIO = os.path.join(ROOT, 'language-teacher', 'audio')
WIN = 240            # 10ms (24000 Hz)
TAIL_WINDOWS = 3     # 마지막 30ms
LIMIT_DB = -45.0


def ffmpeg():
    exe = shutil.which('ffmpeg')
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit('ffmpeg가 없어요. `pip install imageio-ffmpeg` 후 다시 실행하세요.')


def rms_db(s):
    r = math.sqrt(sum(x * x for x in s) / len(s)) if len(s) else 0
    return 20 * math.log10(r / 32768) if r else -120.0


def check(ff, path):
    p = subprocess.run([ff, '-v', 'error', '-i', path, '-f', 's16le', '-ac', '1', '-ar', '24000', '-'], capture_output=True)
    a = array.array('h', p.stdout)
    if p.returncode or len(a) < WIN * (TAIL_WINDOWS + 1):
        return path, len(a) / 24000, 0.0, '읽기 실패' if p.returncode else '너무 짧음'
    tail = max(rms_db(a[len(a) - WIN * (k + 1):len(a) - WIN * k]) for k in range(TAIL_WINDOWS))
    return path, len(a) / 24000, tail, '끝 잘림' if tail > LIMIT_DB else ''


def main():
    ap = argparse.ArgumentParser(description='녹음 끝 잘림 검사')
    ap.add_argument('--lang', default='', help='en,zh,... (기본: 전부)')
    ap.add_argument('--delete', action='store_true', help='의심 파일 지우기')
    ap.add_argument('--dir', default=AUDIO, help='audio 폴더(기본: language-teacher/audio)')
    args = ap.parse_args()
    ff = ffmpeg()
    langs = [l for l in args.lang.split(',') if l] or sorted(d for d in os.listdir(args.dir) if os.path.isdir(os.path.join(args.dir, d)))
    files = [os.path.join(args.dir, l, f) for l in langs for f in sorted(os.listdir(os.path.join(args.dir, l))) if f.endswith('.mp3')]
    with ThreadPoolExecutor(os.cpu_count() or 4) as ex:
        res = list(ex.map(lambda f: check(ff, f), files))
    bad = [r for r in res if r[3]]
    for l in langs:
        n = sum(1 for r in res if os.path.basename(os.path.dirname(r[0])) == l)
        b = sum(1 for r in bad if os.path.basename(os.path.dirname(r[0])) == l)
        print(f'{l}: {n}개 중 의심 {b}개')
    for path, dur, tail, why in bad:
        print(f'  {os.path.relpath(path, args.dir)}  {dur:.2f}초  끝 {tail:.0f}dB  {why}')
        if args.delete:
            os.remove(path)
    if bad and args.delete:
        print(f'{len(bad)}개를 지웠어요 → node tools/tts/generate.mjs 로 다시 녹음하세요.')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
