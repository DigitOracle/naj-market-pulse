// Static preview harness: evaluates the Worker's render functions against the pushed board data so the new pages can be
// looked at before Kendall deploys. Writes home.html and dev_<key>.html next to this file.
import fs from "node:fs"; import vm from "node:vm"; import path from "node:path";
const src = fs.readFileSync("C:/Dev/azimuth-worker/src/index.js", "utf8").replace(/^export default/m, "const __mod =");
const ctx = { console, URL, TextEncoder, TextDecoder, setTimeout, clearTimeout, atob, btoa, fetch: async () => ({ ok: false }), crypto: globalThis.crypto };
vm.createContext(ctx);
vm.runInContext(src + "\nglobalThis.__x = { renderHome, renderDev, renderCompare };", ctx);
const bd = JSON.parse(fs.readFileSync("C:/Dev/naj-market-pulse/data/board/board_devs.json", "utf8"));
const key = "PREVIEW";
const dir = path.dirname(new URL(import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, "$1"));
fs.writeFileSync(path.join(dir, "home.html"), ctx.__x.renderHome(bd, key));
for (const dv of bd.developers) fs.writeFileSync(path.join(dir, "dev_" + dv.key + ".html"), ctx.__x.renderDev(dv, bd, dv.key === "imtiaz" ? { symphony: { cards: new Array(7) } } : {}, key));
const cmp = JSON.parse(fs.readFileSync("C:/Dev/naj-market-pulse/data/board/dev_compare.json", "utf8"));
fs.writeFileSync(path.join(dir, "compare.html"), ctx.__x.renderCompare(cmp, bd, { a: "", b: "", bed: "all", band: "all", diff: false }, key));
fs.writeFileSync(path.join(dir, "compare_pick.html"), ctx.__x.renderCompare(cmp, bd, { a: "imtiaz", b: "", bed: "all", band: "all", diff: false }, key));
fs.writeFileSync(path.join(dir, "compare_imtiaz_ellington.html"), ctx.__x.renderCompare(cmp, bd, { a: "imtiaz", b: "ellington", bed: "1", band: "1to2", diff: false }, key));
console.log("preview written:", fs.readdirSync(dir).filter(f => f.endsWith(".html")).length, "pages");
