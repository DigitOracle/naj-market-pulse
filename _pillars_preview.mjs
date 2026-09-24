// Render the pillars card exactly as the live pages do, from the files now on the live store.
// Uses the Worker's own buildingData + pillars module, so this is the page's output, not a mock-up.
import fs from "node:fs";
import { buildingData } from "file:///C:/Dev/azimuth-worker-dewa/src/building_page.js";
import { buildingPillars, pillarsCard, developerPillarsCard, PILLAR_CSS } from "file:///C:/Dev/azimuth-worker-dewa/src/pillars.js";

const NAJ = "C:/Dev/naj-market-pulse/data";
const rd = (f) => { try { return JSON.parse(fs.readFileSync(f, "utf8")); } catch (e) { return null; } };
const pill = rd(NAJ + "/board/pillars.json");
const cards = [];

const show = (slug, ids, label) => {
  const stack = rd(`${NAJ}/board/stack_${slug}.json`);
  const umx = rd(`${NAJ}/board/unitmix_${slug}.json`);
  if (!stack || !umx) return;
  const bf = rd(`${NAJ}/board/bldgfacts_${slug}.json`);
  const anchors = rd(`${NAJ}/names/anchors_${slug}.json`);
  const area = ((stack.district_amenities || {}).centre || {}).label || slug;
  for (const id of ids) {
    let D = null;
    try { D = buildingData(slug, id, stack, umx, bf, anchors, null, area, null, null, null); } catch (e) { continue; }
    if (!D) continue;
    const { axes, price, dev, name } = buildingPillars(D, pill, area);
    const scored = axes.filter((a) => a.value != null).length;
    console.log(`${String(id).padStart(5)}  ${D.name.slice(0, 30).padEnd(30)} ${scored}/3  ${name ? name.slice(0, 38) : "no developer"}`);
    cards.push(`<h2>${D.name} <small>${D.district} · ${label}</small></h2>` + pillarsCard({
      axes, price, subtitle: name || "developer not named in the register",
      sourceLine: "DLD project and developer registers, DLD transactions, RTA stations, KHDA schools, DHA facilities.",
    }));
  }
};

// Business Bay: the building Azimuth checked on live, plus ones that exercise each state
const bb = rd(`${NAJ}/board/stack_businessbay.json`).buildings_by_id;
const withDev = Object.entries(bb).filter(([, v]) => v.project && v.project.developer_no).map(([k]) => k);
show("businessbay", ["7", "574"].concat(withDev.filter((k) => !["7", "574"].includes(k)).slice(0, 1)), "developer joined");
show("businessbay", ["12"], "developer known, too few projects to score");

// a district that only gained its developer join in today's push
const dm = rd(`${NAJ}/board/stack_dubaimarina.json`).buildings_by_id;
show("dubaimarina", Object.entries(dm).filter(([, v]) => v.project && v.project.developer_no).map(([k]) => k).slice(0, 2), "new in today's push");

// a thin page - what most of the 66,714 building pages look like
{
  const thin = buildingPillars({ name: "Unnamed building", district: "", register: [], transit: [], project: null }, pill, "");
  const html = pillarsCard({ axes: thin.axes, price: thin.price, subtitle: "nothing on this building yet", sourceLine: "DLD registers." });
  console.log(`\n  thin page  Unnamed building              0/3  -> ${/<svg/.test(html) ? "CHART (wrong)" : "no chart, states itself"}`);
  cards.push('<h2>Unnamed building <small>a thin page · most of the 66,714</small></h2>' + html);
}

// the grouped developer card, as /dev draws it
const grp = (pill.groups || {});
for (const key of ["Emaar", "Sobha"]) {
  const g = grp[key];
  if (!g) continue;
  console.log(`  /dev ${key.padEnd(8)} ${g.entities} entities, ${g.projects.total} projects, track ${g.track}, on time ${g.on_time_pct}%${g.registerShortOf ? "  (portfolio says " + g.registerShortOf + ")" : ""}`);
  cards.push(`<h2>${key} <small>the developer card, as /dev draws it</small></h2>` + developerPillarsCard(g));
}

fs.writeFileSync("pillars_preview.html", `<!doctype html><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>The pillars — live</title>
<link rel=stylesheet href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>:root{--gold:#C5A56A;--ink:#0C1413;--mut:#8FA39B;--text:#E8E4D8;--line:rgba(197,165,106,.38);--panel:rgba(19,31,29,.94)}
body{background:var(--ink);color:var(--text);font-family:"IBM Plex Sans",system-ui,sans-serif;margin:0;padding:18px 14px 60px;max-width:430px;margin-inline:auto}
h1{font-family:Fraunces,Georgia,serif;font-size:1.5rem;margin:0 0 4px}h1 em{font-style:normal;color:var(--gold)}
.intro{color:var(--mut);font-size:.78rem;line-height:1.5;margin-bottom:8px}
h2{font-family:Fraunces,Georgia,serif;font-size:1.1rem;margin:28px 0 0}
h2 small{display:block;font:400 .6rem/1.6 "IBM Plex Mono",monospace;color:var(--mut);letter-spacing:.08em;text-transform:uppercase}
${PILLAR_CSS}</style>
<h1>The <em>pillars</em></h1>
<div class=intro>Rendered by the Worker's own code from the files now on the live store. Not a screenshot of the wire.</div>
${cards.join("")}`);
console.log("\n-> pillars_preview.html");
