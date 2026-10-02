#!/usr/bin/env python3
"""중국어 말하기 채점용 병음 사전 만들기 → language-teacher/speech-zh.js

인식기가 돌려준 한자가 목표 글자와 다를 때, 같은 소리(같은 병음·성조)인지, 성조만 다른지, 소리가 다른지를 앱이 알 수 있게
글자마다 병음(성조 표시)을 담아요. 대상: 자주 쓰는 한자(GB2312 1급 3,755자) + 학습 데이터·이야기에 나오는 모든 한자.
여러 소리를 가진 글자는 흔한 순서로 3개까지.

  pip install pypinyin
  python3 tools/speech/build-zh.py          # 만든 뒤 node tools/stamp-data-ver.mjs 로 DATA_VER 갱신
"""
import json, os, re, sys
from pypinyin import pinyin, Style

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'language-teacher')
HAN = re.compile(r'[一-鿿]')

chars = set()
for hi in range(0xB0, 0xD8):                      # GB2312 1급: 첫 바이트 B0~D7
    for lo in range(0xA1, 0xFF):
        try: c = bytes([hi, lo]).decode('gb2312')
        except UnicodeDecodeError: continue
        if HAN.match(c): chars.add(c)
level1 = len(chars)
for f in ('data-zh.js', 'stories-zh.js'):
    with open(os.path.join(ROOT, f), encoding='utf8') as fh: chars.update(HAN.findall(fh.read()))

# 다른 소리는 실제로 쓰이는 것만: pypinyin 구(낱말) 사전에서 그 소리로 읽히는 낱말이 5개 이상이고 그 글자 쓰임의 4% 이상일 때.
# 옛·희귀 독음(吃 qī, 大 tài, 见 xiàn, 会 kuài, 平 pián)을 넣으면 인식기가 적은 다른 글자(七←吃)가 같은 소리로 통과해 버린다
from collections import Counter, defaultdict
from pypinyin.phrases_dict import phrases_dict
use = defaultdict(Counter)
for ph, pys in phrases_dict.items():
    if len(ph) == len(pys):
        for ch, p in zip(ph, pys): use[ch][p[0]] += 1
def common(c, r):
    tot = sum(use[c].values())
    return tot > 0 and use[c][r] >= 5 and use[c][r] / tot >= 0.04

groups, extra = {}, {}   # groups: 글자마다 가장 흔한 소리, extra: 그 밖의 소리(실제로 쓰이는 것만 2개까지)
for c in sorted(chars):
    rs = []
    for r in pinyin(c, style=Style.TONE, heteronym=True)[0]:
        r = r.strip().lower()
        if r and re.fullmatch(r'[a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜüńňǹḿ]+', r) and r not in rs: rs.append(r)
    rs = rs[:1] + [r for r in rs[1:] if common(c, r)]
    for k, r in enumerate(rs[:3]): (groups if k == 0 else extra).setdefault(r, []).append(c)
if not groups: sys.exit('병음을 하나도 못 만들었어요')
out = {k: ''.join(v) for k, v in sorted(groups.items())}
out2 = {k: ''.join(v) for k, v in sorted(extra.items())}
body = ('// 중국어 말하기 채점용 병음 사전 (자동 생성: tools/speech/build-zh.py — 직접 고치지 마세요)\n'
        '// py: { 병음(성조 표시): 그 소리가 가장 흔한 글자들 }, py2: 같은 글자의 다른 소리(실제로 쓰이는 것만 2개까지)\n'
        'window.SPEECH_ZH = ' + json.dumps({'v': 1, 'py': out, 'py2': out2}, ensure_ascii=False, separators=(',', ':')) + ';\n')
path = os.path.join(ROOT, 'speech-zh.js')
with open(path, 'w', encoding='utf8') as fh: fh.write(body)
print(f'글자 {len(chars)}개(1급 {level1}) · 소리 {len(set(out) | set(out2))}개 · {len(body.encode("utf8")) // 1024} KB → {os.path.relpath(path)}')
