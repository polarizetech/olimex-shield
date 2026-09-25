/* dev_check_js.mjs -- the playback helpers. `node apps/web/dev_check_js.mjs` */
import { envelope, indexAt, nextTag, prevTag, robustRange, fmtTime } from "./playback.js";

let pass = 0; const fail = [];
const ok = (n, c, note = "") => (c ? pass++ : fail.push(`${n}${note ? " -- " + note : ""}`));

// An overview must keep a one-sample spike however long the record -- a stride would drop it.
const long = new Array(100000).fill(0); long[73129] = 900;
const env = envelope(long, 300);
ok("envelope has one column per pixel", env.length === 300);
ok("a single-sample spike survives min/max decimation", env.some((c) => c.max === 900));
ok("...and lands in the right column", env[Math.floor(73129 / (100000 / 300))].max === 900);
ok("every sample is covered", envelope([1, 2, 3, 4, 5, 6, 7], 3).reduce((a, c) => a + (c.max >= c.min), 0) === 3);
ok("an empty record gives an empty envelope", envelope([], 10).length === 0);

ok("indexAt clamps below 0", indexAt(-1, 250, 1000) === 0);
ok("indexAt clamps past the end", indexAt(99, 250, 1000) === 1000);
ok("indexAt maps seconds at the DECLARED rate", indexAt(2, 250, 1000) === 500);

const tags = [{ t_s: 5, label: "b" }, { t_s: 1, label: "a" }, { t_s: 9, label: "c" }];
ok("nextTag finds the next tag regardless of stored order", nextTag(tags, 1).label === "b");
ok("nextTag is null after the last", nextTag(tags, 9) === null);
ok("prevTag finds the previous tag", prevTag(tags, 6).label === "b");
ok("prevTag skips a tag the playhead is sitting on", prevTag(tags, 5.1).label === "a");

const rr = robustRange([...new Array(999).fill(0).map((_, i) => Math.sin(i / 10)), 5000]);
ok("a single blink does not flatten the scale", rr.half < 10, JSON.stringify(rr));
ok("fmtTime formats m:ss.s", fmtTime(65.25) === "1:05.3", fmtTime(65.25));

for (const f of fail) console.log(`  FAIL ${f}`);
console.log(`[js] ${pass} passed, ${fail.length} failed`);
process.exit(fail.length ? 1 : 0);
