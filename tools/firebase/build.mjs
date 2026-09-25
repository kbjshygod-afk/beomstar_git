// 사용법: cd tools/firebase && npm install && npm run build
// → language-teacher/vendor/firebase/ 에 fb-core.js · fb-sync.js · fb-shared-*.js 생성(ESM, 코드 분할)
// → 만든 파일들의 내용 해시(8자리)를 language-teacher/index.html 의 FB_VER 에 자동으로 적는다(캐시 무효화)
//   SDK 버전이 같아도 내보내기(fb-core.js·fb-sync.js)를 바꿔 다시 묶으면 해시가 바뀌므로, 옛 묶음과 새 묶음이 섞이지 않는다
// SDK 버전 올리기: package.json 의 "firebase" 버전을 바꾸거나(npm install firebase@<새 버전> -D -E) → npm install → npm run build
// 확인만(설치 없이): node tools/firebase/build.mjs --check   (FB_VER가 지금 묶음과 다르면 실패)
// 다시 묶지 않고 FB_VER만 적기(설치 없이): node tools/firebase/build.mjs --stamp   (예: 병합 뒤 FB_VER 줄이 어긋났을 때)
import { rmSync, mkdirSync, readFileSync, writeFileSync, readdirSync } from 'node:fs';
import { createHash } from 'node:crypto';
const out = new URL('../../language-teacher/vendor/firebase/', import.meta.url);
const idx = new URL('../../language-teacher/index.html', import.meta.url);
const check = process.argv.includes('--check'), stampOnly = process.argv.includes('--stamp');

if (!check && !stampOnly) {
  const { build } = await import('esbuild');
  const ver = JSON.parse(readFileSync(new URL('./node_modules/firebase/package.json', import.meta.url))).version;
  rmSync(out, { recursive: true, force: true });
  mkdirSync(out, { recursive: true });
  await build({
    entryPoints: [new URL('fb-core.js', import.meta.url).pathname, new URL('fb-sync.js', import.meta.url).pathname],
    bundle: true, minify: true, format: 'esm', splitting: true, target: 'es2019',
    outdir: out.pathname, chunkNames: 'fb-shared-[hash]', legalComments: 'eof',
    banner: { js: '/*! Firebase JS SDK v' + ver + ' (Apache-2.0) — 랭귀지 스타터용 묶음 */' },
  });
  console.log('built Firebase', ver, '→', out.pathname);
}

// 묶음 파일 전체(이름+내용)의 해시 → FB_VER
const files = readdirSync(out).filter(f => f.endsWith('.js')).sort();
if (!files.length) { console.error('vendor/firebase 에 묶음 파일이 없어요'); process.exit(2); }
const h = createHash('sha1');
files.forEach(f => { h.update(f); h.update(readFileSync(new URL(f, out))); });
const fbVer = h.digest('hex').slice(0, 8);
const html = readFileSync(idx, 'utf8');
const m = html.match(/const FB_VER = '([^']*)';/);
if (!m) { console.error('index.html 에서 FB_VER 줄을 찾지 못했어요'); process.exit(2); }
if (m[1] === fbVer) { console.log('FB_VER 최신:', fbVer, '(' + files.join(', ') + ')'); process.exit(0); }
if (check) { console.error('FB_VER가 묶음과 달라요:', m[1], '→', fbVer, '(cd tools/firebase && npm run build 또는 node tools/firebase/build.mjs --stamp)'); process.exit(1); }
writeFileSync(idx, html.replace(m[0], "const FB_VER = '" + fbVer + "';"));
console.log('FB_VER', m[1], '→', fbVer, '(' + files.join(', ') + ')');
