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
# 채점용 띄어쓰기(ja-spacing.json): 띄어 쓴 글에서 공백만 빼면 원래 글과 같아야 하고, 원래 글은 학습 데이터에 있어야 해요
spacing = {k: v for k, v in json.load(open(os.path.join(HERE, 'ja-spacing.json'), encoding='utf8')).items() if k != '_'}
for k, v in spacing.items():
    if re.sub(r'\s', '', v) != re.sub(r'\s', '', k): errs.append(f'띄어쓰기 {k!r}: 공백을 빼면 원래 글과 달라요')
    if k not in src: errs.append(f'띄어쓰기 {k!r}: 학습 데이터에 없는 글이에요')
if errs:
    for e in errs: print('오류', e)
    sys.exit(f'오류 {len(errs)}건 — 고친 뒤 다시 실행하세요')
# 학습 문장에 없어도 초보가 자주 말할(인식기가 한자로 적을) 낱말 — 없으면 '직접 확인'으로 넘어가서 틀린 곳을 못 짚는다
EXTRA = {'足': 'た|あし', '大': 'おお|だい', '小': 'ちい|しょう', '大学': 'だいがく', '大学生': 'だいがくせい', '高校生': 'こうこうせい', '犬': 'いぬ', '猫': 'ねこ',
         '病院': 'びょういん', '銀行': 'ぎんこう', '図書館': 'としょかん', '郵便局': 'ゆうびんきょく', '公園': 'こうえん', '空港': 'くうこう', '映画館': 'えいがかん',
         '友達': 'ともだち', '家族': 'かぞく', '父': 'ちち', '母': 'はは', '兄': 'あに', '姉': 'あね', '弟': 'おとうと', '妹': 'いもうと',
         '朝': 'あさ', '昼': 'ひる', '夜': 'よる', '晩': 'ばん', '毎朝': 'まいあさ', '毎晩': 'まいばん', '今': 'いま', '今週': 'こんしゅう', '来週': 'らいしゅう', '先週': 'せんしゅう',
         '車': 'くるま', '自転車': 'じてんしゃ', '飛行機': 'ひこうき', '魚': 'さかな', '肉': 'にく', '野菜': 'やさい', '果物': 'くだもの', '卵': 'たまご', '牛乳': 'ぎゅうにゅう',
         '新聞': 'しんぶん', '雑誌': 'ざっし', '手紙': 'てがみ', '写真': 'しゃしん', '部屋': 'へや', '家': 'いえ|うち', '店': 'みせ', '天気': 'てんき', '雨': 'あめ', '雪': 'ゆき',
         '暑': 'あつ', '寒': 'さむ', '覚醒': 'かくせい', '吸入': 'きゅうにゅう', '岡': 'おか'}
for k, v in EXTRA.items():
    for r in v.split('|'):
        if r not in dic.setdefault(k, []): dic[k].append(r)
out = {k: '|'.join(v) for k, v in sorted(dic.items())}
body = ('// 일본어 말하기 채점용 한자 읽기 사전 (자동 생성: tools/speech/build-ja.py — 직접 고치지 마세요)\n'
        '// { 한자 덩어리: 읽기(여러 개면 |로) } — 인식기가 한자로 돌려준 글을 가나로 되돌려 학습 문장과 비교\n'
        '// sp: { 띄어쓰기 없는 학습 문장: 채점용 띄어쓰기 } — 덩어리 끝 조사 자리(빠져도 긴 문장에선 봐줌)\n'
        'window.SPEECH_JA = ' + json.dumps({'v': 1, 'k': out, 'sp': dict(sorted(spacing.items()))}, ensure_ascii=False, separators=(',', ':')) + ';\n')
path = os.path.join(ROOT, 'speech-ja.js')
with open(path, 'w', encoding='utf8') as fh: fh.write(body)
print(f'문장 {len(items)}개 · 한자 덩어리 {len(out)}개 · 띄어쓰기 {len(spacing)}개 · {len(body.encode("utf8")) // 1024} KB → {os.path.relpath(path)}')
if missing: print(f'⚠️ 원본에 없는 말하기 문장 {len(missing)}개(한자로 알아들으면 직접 확인으로 넘어가요):', missing[:20])
