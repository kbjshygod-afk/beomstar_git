#!/usr/bin/env python3
"""일본어 말하기 채점용 한자 읽기 사전 만들기 → language-teacher/speech-ja.js

학습 문장은 가나로만 쓰여 있는데, 음성 인식기는 「私は学生です」처럼 한자로 돌려줘요. 그래서 앱이 들린 글의 한자를
가나로 되돌려 목표 문장과 글자 단위로 맞춰 볼 수 있게, 한자 덩어리 → 읽기 사전을 만들어요.

원본: tools/speech/ja-spellings.json — 말하기 문장마다 인식기가 돌려줄 법한 표기와 그 안의 한자 덩어리 읽기
      [{"kana": 학습 문장, "spellings": [{"text": 표기, "readings": {"한자덩어리": "읽기"}}]}]
검사: 한자 덩어리를 읽기로 바꿔 끼우면 학습 문장과 똑같아야 해요(띄어쓰기·문장부호·가타카나/히라가나 차이 무시).
      학습 데이터(data-ja.js)의 말하기 문장이 원본에 빠져 있으면 알려 줘요(새 문장을 넣었으면 원본에 추가).

  python3 tools/speech/build-ja.py          # 만든 뒤 node tools/stamp-data-ver.mjs 로 DATA_VER 갱신
"""
import json, os, re, sys, unicodedata
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..', '..', 'language-teacher')
RUN = re.compile(r'[一-鿿々〆ヶ]+')
def norm(t):
    t = unicodedata.normalize('NFKC', t)
    t = ''.join(chr(ord(c) - 0x60) if 'ァ' <= c <= 'ヶ' else c for c in t)
    return re.sub(r'[\s、。！？!?,.・…「」『』（）()〜~]', '', t)
items = json.load(open(os.path.join(HERE, 'ja-spellings.json'), encoding='utf8'))
errs, dic = [], {}
for it in items:
    for sp in it['spellings']:
        text, rd = sp['text'], sp.get('readings') or {}
        runs = RUN.findall(text)
        miss = [r for r in runs if r not in rd]
        if miss: errs.append(f"{it['kana']!r}: {text!r} 읽기 없는 한자 {miss}"); continue
        if norm(RUN.sub(lambda m: rd[m.group(0)], text)) != norm(it['kana']):
            errs.append(f"{it['kana']!r}: {text!r} 읽기로 바꾸면 학습 문장과 달라요"); continue
        for r in runs:
            v = norm(rd[r])
            if v and v not in dic.setdefault(r, []): dic[r].append(v)
# 학습 데이터의 말하기 문장(단어·핵심 문장·대화)이 원본에 다 있는지
src = open(os.path.join(ROOT, 'data-ja.js'), encoding='utf8').read()
data = json.loads(src[src.index('{'):src.rindex('}') + 1])
need = set()
for u in data['units']:
    for l in u['lessons']:
        for x in (l.get('words') or []) + (l.get('keySentences') or []) + ((l.get('dialogue') or {}).get('turns') or []): need.add(x['ja'])
missing = sorted(need - {it['kana'] for it in items})
for e in errs: print('오류', e)
if errs: sys.exit(f'오류 {len(errs)}건 — 고친 뒤 다시 실행하세요')
out = {k: '|'.join(v) for k, v in sorted(dic.items())}
body = ('// 일본어 말하기 채점용 한자 읽기 사전 (자동 생성: tools/speech/build-ja.py — 직접 고치지 마세요)\n'
        '// { 한자 덩어리: 읽기(여러 개면 |로) } — 인식기가 한자로 돌려준 글을 가나로 되돌려 학습 문장과 비교\n'
        'window.SPEECH_JA = ' + json.dumps({'v': 1, 'k': out}, ensure_ascii=False, separators=(',', ':')) + ';\n')
path = os.path.join(ROOT, 'speech-ja.js')
with open(path, 'w', encoding='utf8') as fh: fh.write(body)
print(f'문장 {len(items)}개 · 한자 덩어리 {len(out)}개 · {len(body.encode("utf8")) // 1024} KB → {os.path.relpath(path)}')
if missing: print(f'⚠️ 원본에 없는 말하기 문장 {len(missing)}개(한자로 알아들으면 직접 확인으로 넘어가요):', missing[:20])
