// Regenerates score_js_cases.json from lesson 8's score.js, the reference that
// app/stage.py ports. Not run in CI (CI has no lesson 8 folder); run it by hand:
//   node tests/fixtures/make_score_js_cases.mjs <path to aido-lesson8-business-stage>
import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';

const root = process.argv[2];
if (!root) { console.error('usage: node make_score_js_cases.mjs <lesson8 folder>'); process.exit(1); }
const { scoreBusiness } = await import(pathToFileURL(join(root, 'src', 'score.js')).href);

const fill = (v) => ({ strategy: v[0], management: v[1], systems: v[2], people: v[3], finance: v[4] });
const lesson8 = JSON.parse(readFileSync(join(root, 'evals', 'cases.json'), 'utf8'))
  .map((c) => ({ name: c.name, answers: c.answers }));

const extra = [
  ['all 1 (total 20)', fill([[1,1,1,1],[1,1,1,1],[1,1,1,1],[1,1,1,1],[1,1,1,1]])],
  ['all 3 (total 60)', fill([[3,3,3,3],[3,3,3,3],[3,3,3,3],[3,3,3,3],[3,3,3,3]])],
  ['total 34', fill([[2,2,2,2],[2,2,2,2],[2,2,1,1],[2,2,1,1],[2,2,1,1]])],
  ['total 46', fill([[3,3,3,3],[2,2,2,2],[2,2,2,2],[2,2,2,2],[2,2,3,3]])],
  ['averages 1.25 1.5 1.75 2.25 2.5 (rounding)', fill([[1,1,1,2],[1,1,2,2],[1,2,2,2],[2,2,2,3],[2,2,3,3]])],
  ['averages 2.75 2.0 1.0 3.0 1.75', fill([[2,3,3,3],[2,2,2,2],[1,1,1,1],[3,3,3,3],[2,2,2,1]])],
  ['invalid: answer 4', fill([[4,1,1,1],[1,1,1,1],[1,1,1,1],[1,1,1,1],[1,1,1,1]])],
  ['invalid: answer 0', fill([[1,1,1,1],[0,1,1,1],[1,1,1,1],[1,1,1,1],[1,1,1,1]])],
  ['invalid: 3 answers in a domain', fill([[1,1,1,1],[1,1,1,1],[1,1,1],[1,1,1,1],[1,1,1,1]])],
].map(([name, answers]) => ({ name, answers }));

const cases = [...lesson8, ...extra].map((c) => {
  try { return { ...c, expected: scoreBusiness(c.answers) }; }
  catch (e) { return { ...c, expected: { error: e.message } }; }
});
writeFileSync(new URL('./score_js_cases.json', import.meta.url), JSON.stringify(cases, null, 2) + '\n');
console.log(`wrote ${cases.length} cases`);
