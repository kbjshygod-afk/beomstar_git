// language-teacher/data-*.js · stories-*.js 내용으로 DATA_VER(8자리 해시)를 정해 index.html에 적는다.
// 데이터를 고친 뒤 배포 전에: node tools/stamp-data-ver.mjs        (확인만: node tools/stamp-data-ver.mjs --check)
import { readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
const dir = new URL('../language-teacher/', import.meta.url);
const files = readdirSync(dir).filter(f => /^(data|stories)-[a-z]{2}\.js$/.test(f)).sort();
const h = createHash('sha1');
files.forEach(f => { h.update(f); h.update(readFileSync(new URL(f, dir))); });
const ver = h.digest('hex').slice(0, 8);
const idx = new URL('index.html', dir);
const html = readFileSync(idx, 'utf8');
const m = html.match(/const DATA_VER = '([^']*)';/);
if (!m) { console.error('DATA_VER 줄을 찾지 못했어요'); process.exit(2); }
if (m[1] === ver) { console.log('DATA_VER 최신:', ver); process.exit(0); }
if (process.argv.includes('--check')) { console.error('DATA_VER가 데이터와 달라요:', m[1], '→', ver, '(node tools/stamp-data-ver.mjs 실행)'); process.exit(1); }
writeFileSync(idx, html.replace(m[0], "const DATA_VER = '" + ver + "';"));
console.log('DATA_VER', m[1], '→', ver, '(' + files.length + '개 파일)');
