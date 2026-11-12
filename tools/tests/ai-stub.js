// 시험 전용: 함수 프로세스에서 Gemini·OpenAI 호출만 가짜 응답으로 바꾼다(그 밖의 요청은 그대로).
const real = globalThis.fetch;
globalThis.__aiCalls = [];
globalThis.fetch = async (url, opts) => {
  const u = String(url), body = opts && opts.body ? String(opts.body) : '';
  const json = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { 'content-type': 'application/json' } });
  if (u.includes('generativelanguage.googleapis.com')) {
    if (body.includes('FAILGEMINI')) return json(429, {});
    if (body.includes('BADKEY')) return json(403, {});
    return json(200, { candidates: [{ content: { parts: [{ text: '[gemini] ' + (JSON.parse(body).contents.slice(-1)[0].parts[0].text) }] } }] });
  }
  if (u.includes('api.openai.com')) {
    if (body.includes('FAILOPENAI')) return json(500, {});
    return json(200, { choices: [{ message: { content: '[openai] ' + (JSON.parse(body).messages.slice(-1)[0].content) } }] });
  }
  return real(url, opts);
};
