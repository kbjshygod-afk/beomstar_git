#!/usr/bin/env python3
"""녹음 소리 크기 맞추기 — 모든 클립을 같은 크기(기본 -15 LUFS, 휴대폰 영상·팟캐스트 수준)로.

Google TTS 녹음은 언어·문장마다 -16~-27 LUFS로 들쭉날쭉하고, 휴대폰 스피커로 들으면 작아요.
EBU R128 크기를 재서 그만큼 키우고, 튀는 최고점은 리미터로 -1.5 dBTP 아래로 눌러 찢어지지 않게 해요.

  python3 tools/tts/loudness.py              # 전부(이미 맞춘 파일은 건너뜀)
  python3 tools/tts/loudness.py --lang en    # 고른 언어만
  python3 tools/tts/loudness.py --dry-run    # 재기만

바뀐 파일이 있으면 index.json의 gen을 1 올리고 rev를 다시 계산해요(generate.mjs와 같은 공식) →
한 번 들은 사용자도 새 파일을 받아요. generate.mjs로 새로 녹음한 뒤에도 이것을 한 번 돌려 주세요.
ffmpeg가 필요해요(없으면 `pip install imageio-ffmpeg`).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from check import AUDIO, ffmpeg

BITRATE = '40k'   # 원본 32k를 다시 만들 때 생기는 손실을 줄이려고 조금 높게


def measure(ff, path):
    p = subprocess.run([ff, '-hide_banner', '-nostats', '-i', path, '-af', 'loudnorm=print_format=json', '-f', 'null', '-'], capture_output=True, text=True)
    m = re.search(r'\{[^{}]*"input_i"[^{}]*\}', p.stderr)
    if p.returncode or not m:
        return None
    j = json.loads(m.group(0))
    try:
        return {k: float(j[k]) for k in ('input_i', 'input_tp', 'input_lra', 'input_thresh', 'target_offset')}
    except (KeyError, ValueError):
        return None   # 너무 짧거나 소리가 없음(-inf)


def peak(ff, path):
    p = subprocess.run([ff, '-hide_banner', '-nostats', '-i', path, '-af', 'volumedetect', '-f', 'null', '-'], capture_output=True, text=True)
    m = re.search(r'max_volume: (-?[\d.]+|-inf) dB', p.stderr)
    return float(m.group(1)) if m else None


TAG = 'lt-loud'   # 한 번 맞춘 파일 표시(ID3 comment) — 다시 돌려도 두 번 변환하지 않게(음질)


def tagged(ff, path):
    p = subprocess.run([ff, '-hide_banner', '-i', path], capture_output=True, text=True)
    return TAG in p.stderr


def normalize(ff, path, target, tp, dry):
    if tagged(ff, path):
        return path, None, None, ''
    m = measure(ff, path)
    if m and float('-inf') < m['input_i'] < -45:   # 잴 수는 있는데 아주 작음(-inf는 너무 짧아서 못 잰 것 → 아래에서 최고점으로)
        return path, m['input_i'], None, '소리 없음'
    if not m or m['input_i'] == float('-inf'):
        # 0.4초보다 짧으면 크기를 잴 수 없다 — 소리가 거의 없으면(최고점 -30dB 아래) 망가진 녹음, 아니면 그대로 둔다
        pk = peak(ff, path)
        return path, None, None, '소리 없음' if pk is None or pk < -30 else ''
    if abs(m['input_i'] - target) <= 1.5 and m['input_tp'] <= tp + 0.3:
        return path, m['input_i'], m['input_i'], ''
    if dry:
        return path, m['input_i'], None, '바꿀 것'
    # 그만큼 키우고 튀는 최고점만 리미터로 눌러 준다. 리미터가 깎은 만큼을 한 번 더 재서 보탠다(문장마다 같은 크기로)
    chain = lambda g: 'volume={g:.2f}dB,alimiter=limit={lim:.4f}:attack=5:release=50:level=0'.format(g=g, lim=10 ** ((tp - 0.5) / 20))
    gain = max(-6.0, min(12.0, target - m['input_i']))
    wav = path + '.tmp.wav'
    p = subprocess.run([ff, '-hide_banner', '-v', 'error', '-y', '-i', path, '-af', chain(gain), wav], capture_output=True, text=True)
    m2 = measure(ff, wav) if not p.returncode else None
    if os.path.exists(wav):
        os.remove(wav)
    if m2:
        gain = max(-6.0, min(14.0, gain + (target - m2['input_i'])))
    af = chain(gain)
    tmp = path + '.tmp.mp3'
    p = subprocess.run([ff, '-hide_banner', '-v', 'error', '-y', '-i', path, '-af', af, '-ar', '24000', '-ac', '1', '-c:a', 'libmp3lame', '-b:a', BITRATE, '-map_metadata', '-1', '-metadata', 'comment=' + TAG + '=' + str(target), tmp], capture_output=True, text=True)
    if p.returncode or not os.path.exists(tmp):
        if os.path.exists(tmp):
            os.remove(tmp)
        return path, m['input_i'], None, '만들기 실패: ' + p.stderr.strip()[:200]
    after = measure(ff, tmp)
    os.replace(tmp, path)
    return path, m['input_i'], after['input_i'] if after else None, 'changed'


def rev_for(voices, rates, gen):
    # generate.mjs의 revFor와 같은 값: sha1(JSON.stringify([voices.a, voices.b, rates.a, rates.b, gen]))
    s = json.dumps([voices.get('a'), voices.get('b'), rates.get('a'), rates.get('b'), gen], separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha1(s.encode('utf-8')).hexdigest()[:10]


def main():
    ap = argparse.ArgumentParser(description='녹음 소리 크기 맞추기')
    ap.add_argument('--lang', default='', help='en,zh,... (기본: 전부)')
    ap.add_argument('--target', type=float, default=-15.0, help='목표 크기 LUFS(기본 -15)')
    ap.add_argument('--tp', type=float, default=-1.5, help='최고점 한계 dBTP(기본 -1.5)')
    ap.add_argument('--dry-run', action='store_true', help='재기만 하고 바꾸지 않음')
    ap.add_argument('--drop-silent', action='store_true', help='소리가 거의 없는 녹음을 지우고 index.json에서 빼기')
    ap.add_argument('--dir', default=AUDIO, help='audio 폴더(기본: language-teacher/audio)')
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    args = ap.parse_args()
    ff = ffmpeg()
    langs = [l for l in args.lang.split(',') if l] or sorted(d for d in os.listdir(args.dir) if os.path.isdir(os.path.join(args.dir, d)))
    bad = 0
    for lang in langs:
        d = os.path.join(args.dir, lang)
        files = sorted(os.path.join(d, f) for f in os.listdir(d) if re.fullmatch(r'[0-9a-f]{12}\.mp3', f))
        with ThreadPoolExecutor(args.jobs) as ex:
            res = list(ex.map(lambda f: normalize(ff, f, args.target, args.tp, args.dry_run), files))
        before = [r[1] for r in res if r[1] is not None]
        after = [r[2] for r in res if r[2] is not None]
        changed = [r for r in res if r[3] == 'changed']
        fails = [r for r in res if r[3] and r[3] not in ('changed', '바꿀 것', '소리 없음')]
        silent = [r for r in res if r[3] == '소리 없음']
        todo = [r for r in res if r[3] == '바꿀 것']
        bad += len(fails)
        rng = lambda xs: f'{min(xs):.1f}~{max(xs):.1f}' if xs else '-'
        print(f'{lang}: {len(files)}개 · 원래 {rng(before)} LUFS · 바꾼 것 {len(changed) or len(todo)}개' + (f' → {rng(after)} LUFS' if changed else '') + (f' · 실패 {len(fails)}개' if fails else ''))
        for path, _, _, why in fails[:10]:
            print(f'  {os.path.relpath(path, args.dir)}  {why}')
        if silent:
            # Chirp 목소리는 한 글자·짧은 낱말(す, oui, hey)을 거의 소리 없이 만들 때가 있다 → 지워서 앱이 기기 음성으로 읽게
            print(f'  소리 없는 녹음 {len(silent)}개' + (' → 지우고 목록에서 뺐어요(앱은 기기 음성으로 읽어요)' if args.drop_silent and not args.dry_run else ' (--drop-silent로 지우기)'))
            if args.drop_silent and not args.dry_run:
                gone = {os.path.basename(r[0])[:-4] for r in silent}
                for r in silent:
                    os.remove(r[0])
                ip = os.path.join(d, 'index.json')
                with open(ip, encoding='utf-8') as f:
                    idx = json.load(f)
                idx['ids'] = [i for i in idx.get('ids', []) if i not in gone]
                with open(ip + '.tmp', 'w', encoding='utf-8') as f:
                    f.write(json.dumps(idx, separators=(',', ':'), ensure_ascii=False) + '\n')
                os.replace(ip + '.tmp', ip)
        if changed and not args.dry_run:
            ip = os.path.join(d, 'index.json')
            with open(ip, encoding='utf-8') as f:
                idx = json.load(f)
            gen = (idx.get('gen') if isinstance(idx.get('gen'), int) and idx.get('gen') >= 0 else 0)
            if rev_for(idx.get('voices') or {}, idx.get('rates') or {}, gen) != idx.get('rev'):
                print(f'  ⚠ {lang}: 지금 rev가 공식과 달라요 — gen만 올리고 rev는 새로 계산해요')
            idx['gen'] = gen + 1
            idx['rev'] = rev_for(idx.get('voices') or {}, idx.get('rates') or {}, idx['gen'])
            idx['loud'] = args.target
            with open(ip + '.tmp', 'w', encoding='utf-8') as f:
                f.write(json.dumps(idx, separators=(',', ':'), ensure_ascii=False) + '\n')
            os.replace(ip + '.tmp', ip)
            print(f'  index.json: gen {gen} → {idx["gen"]}, rev {idx["rev"]}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
