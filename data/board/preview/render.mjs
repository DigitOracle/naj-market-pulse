// Static preview harness: evaluates the Worker's render functions against the pushed board data so the new pages can be
// looked at before Kendall deploys. Writes home.html and dev_<key>.html next to this file.
import fs from "node:fs"; import vm from "node:vm"; import path from "node:path";
const src = fs.readFileSync("C:/Dev/azimuth-worker/src/index.js", "utf8").replace(/^export default/m, "const __mod =");
const ctx = { console, URL, TextEncoder, TextDecoder, setTimeout, clearTimeout, atob, btoa, fetch: async () => ({ ok: false }), crypto: globalThis.crypto };
vm.createContext(ctx);
vm.runInContext(src + "\nglobalThis.__x = { renderHome, renderDev, renderCompare, renderSkyline };", ctx);
const bd = JSON.parse(fs.readFileSync("C:/Dev/naj-market-pulse/data/board/board_devs.json", "utf8"));
const key = "PREVIEW";
const dir = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
fs.writeFileSync(path.join(dir, "home.html"), ctx.__x.renderHome(bd, key));
const cmp0 = JSON.parse(fs.readFileSync("C:/Dev/naj-market-pulse/data/board/dev_compare.json", "utf8"));
fs.writeFileSync(path.join(dir, "home_compare.html"), ctx.__x.renderHome(bd, key, cmp0, { mode: "compare", bed: "2", band: "all", metric: "range", sort: "" }));
fs.writeFileSync(path.join(dir, "home_tier2.html"), ctx.__x.renderHome(bd, key, cmp0, { mode: "compare", bed: "2", band: "2to4", metric: "range", sort: "", tier: "2", life: "" }));
fs.writeFileSync(path.join(dir, "home_tier2_beach.html"), ctx.__x.renderHome(bd, key, cmp0, { mode: "compare", bed: "2", band: "2to4", metric: "range", sort: "1", tier: "2", life: "beach" }));
fs.writeFileSync(path.join(dir, "home_compare_sqm.html"), ctx.__x.renderHome(bd, key, cmp0, { mode: "compare", bed: "1", band: "1to2", metric: "sqm", sort: "1" }));
for (const dv of bd.developers) fs.writeFileSync(path.join(dir, "dev_" + dv.key + ".html"), ctx.__x.renderDev(dv, bd, dv.key === "imtiaz" ? { symphony: { cards: new Array(7) } } : {}, key));
const cmp = JSON.parse(fs.readFileSync("C:/Dev/naj-market-pulse/data/board/dev_compare.json", "utf8"));
fs.writeFileSync(path.join(dir, "compare.html"), ctx.__x.renderCompare(cmp, bd, { a: "", b: "", bed: "all", band: "all", diff: false }, key));
fs.writeFileSync(path.join(dir, "compare_pick.html"), ctx.__x.renderCompare(cmp, bd, { a: "imtiaz", b: "", bed: "all", band: "all", diff: false }, key));
fs.writeFileSync(path.join(dir, "compare_imtiaz_ellington.html"), ctx.__x.renderCompare(cmp, bd, { a: "imtiaz", b: "ellington", bed: "1", band: "1to2", diff: false }, key));
// Skyline districts: every district whose packed massing has been copied into img/ as sky_<slug>.
// The same list is the page switcher on each skyline page, so adding a district here adds it everywhere.
const SKY = [{ s: "dubaimarina", n: "Dubai Marina" }, { s: "businessbay", n: "Business Bay" },
             { s: "burjkhalifa", n: "Downtown Dubai" }, { s: "palmjumeirah", n: "Palm Jumeirah" },
             { s: "jumeirahvillagecircle", n: "JVC" }, { s: "palmdeira", n: "Dubai Islands" }];
for (const d of SKY.filter((d) => fs.existsSync(path.join(dir, "img", "sky_" + d.s))))
  fs.writeFileSync(path.join(dir, "skyline_" + d.s + ".html"), ctx.__x.renderSkyline(d.s, d.n, key, SKY));
console.log("preview written:", fs.readdirSync(dir).filter(f => f.endsWith(".html")).length, "pages");
