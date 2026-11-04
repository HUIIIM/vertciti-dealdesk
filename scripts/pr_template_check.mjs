// PR template presence check (SOTA wiring spec 3): verifies the three
// required sections exist and are non-empty in the PR body. Presence
// only - authenticity is judged by the evaluation face, not here.
const token = process.env.GITHUB_TOKEN;
const [owner, repo] = process.env.REPO.split('/');
const number = process.env.PR_NUMBER;
const api = 'https://api.github.com';
const headers = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'User-Agent': 'pr-template-check' };
const prRes = await fetch(`${api}/repos/${owner}/${repo}/pulls/${number}`, { headers });
if (!prRes.ok) { console.error(`GET pull failed: ${prRes.status}`); process.exit(1); }
const pr = await prRes.json();
const body = (pr.body || '').replace(/<!--[\s\S]*?-->/g, '');
const sections = {};
for (const part of body.split(/^##\s+/m).slice(1)) {
  const nl = part.indexOf('\n');
  const title = (nl === -1 ? part : part.slice(0, nl)).trim();
  sections[title] = (nl === -1 ? '' : part.slice(nl + 1)).trim();
}
const required = ['文档影响', '结构结论', '证据指针'];
const missing = required.filter(r => {
  const key = Object.keys(sections).find(k => k.startsWith(r));
  return !key || !sections[key];
});
if (missing.length) {
  await fetch(`${api}/repos/${owner}/${repo}/issues/${number}/comments`, {
    method: 'POST', headers,
    body: JSON.stringify({ body: 'PR 模板在位检查未过：以下必填节缺位或为空 — ' + missing.join('、') + '。请按 PR 模板补齐三节（本检查只查在位非空，真伪归评估面）。' })
  });
  console.error('Missing or empty required PR template sections: ' + missing.join(', '));
  process.exit(1);
}
console.log('All required PR template sections present and non-empty.');
