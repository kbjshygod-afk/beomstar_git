// 사용법: cd tools/firebase && npm install && npm run build
// → language-teacher/vendor/firebase/ 에 fb-core.js · fb-sync.js · fb-shared-*.js 생성(ESM, 코드 분할)
// 버전을 올리면 language-teacher/index.html 의 FB_VER 도 같이 바꿀 것(캐시 무효화)
import { build } from 'esbuild';
import { rmSync, mkdirSync, readFileSync } from 'node:fs';
const out = new URL('../../language-teacher/vendor/firebase/', import.meta.url).pathname;
const ver = JSON.parse(readFileSync(new URL('./node_modules/firebase/package.json', import.meta.url))).version;
rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
await build({
  entryPoints: ['fb-core.js', 'fb-sync.js'],
  bundle: true, minify: true, format: 'esm', splitting: true, target: 'es2019',
  outdir: out, chunkNames: 'fb-shared-[hash]', legalComments: 'eof',
  banner: { js: '/*! Firebase JS SDK v' + ver + ' (Apache-2.0) — 랭귀지 스타터용 묶음 */' },
});
console.log('built Firebase', ver, '→', out);
