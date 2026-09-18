/* Set NAJMA_RESIDENTS_KEY on this machine, by asking for it rather than by being handed it.
 *
 * Unlike CLIENT_KEY, this value cannot be generated: RESIDENTS_KEY already exists as a Wrangler
 * secret on azimuth-2 and gates the private residents page (`rk`). So it has to be typed in - and
 * the obvious way to do that, a setx line with <a placeholder> in it, has now twice been run
 * verbatim, leaving the literal placeholder in the environment. A prompt cannot be copy-pasted
 * wrong.
 *
 * The value is read from the terminal with echo off, never printed, and never put on a command
 * line, so it stays out of shell history. The capture script reads it from HKCU\Environment.
 *
 *   node scripts/set_residents_key.js
 */
"use strict";

/* ---- --new : rotate. Mints a fresh value, sets it on azimuth-2 AND locally, prints Naj's new link. ----
 * Use this only when the existing value cannot be found. RESIDENTS_KEY is single-valued in the
 * worker (residentsKeyOf compares one string; no comma list like CLIENT_KEY), so the moment this
 * runs, the private link Naj already has STOPS WORKING and she needs the one printed below.
 * The value is printed once, here, in Kendall's own terminal - it has to be, it goes into her link -
 * and nowhere else.
 */
if (process.argv.includes("--new")) {
  const { execFileSync } = require("child_process");
  const crypto = require("crypto");
  const v = crypto.randomBytes(24).toString("base64url");           // 32 chars; the worker wants 24+
  // GUARD 1 - never deploy azimuth-2 while one of Naj's pictures is in flight. `wrangler secret put`
  // IS a deploy (it uploads a new version), and a redeploy mid-job loses the picture. Job keys are
  // picjob_* in the MEETINGS namespace; the id is read from the worker's own wrangler.toml, never hardcoded.
  try {
    const toml = require("fs").readFileSync("C:\Dev\azimuth-worker-dewa\wrangler.toml", "utf8");
    const env = toml.slice(toml.indexOf('name = "azimuth-2"'));
    const m = env.match(/binding\s*=\s*"MEETINGS"\s*,\s*id\s*=\s*"([0-9a-f]{32})"/);
    if (!m) { console.error("cannot find the MEETINGS KV namespace id in wrangler.toml - refusing to deploy blind."); process.exit(1); }
    const out = execFileSync("npx", ["wrangler", "kv", "key", "list", "--namespace-id", m[1], "--prefix", "picjob_"], { encoding: "utf8", shell: true, stdio: ["pipe", "pipe", "inherit"] });
    const jobs = JSON.parse(out || "[]");
    if (jobs.length) { console.error("REFUSING: " + jobs.length + " picture job(s) in flight (picjob_*). A secret put redeploys azimuth-2 and would lose them. Try again when the list is empty."); process.exit(1); }
    console.log("no picture jobs in flight - safe to deploy.");
  } catch (e) { console.error("could not check for picture jobs (" + String(e.message).split("\n")[0] + ") - refusing to deploy blind."); process.exit(1); }
  try {
    process.stdout.write("setting RESIDENTS_KEY on azimuth-2 (this invalidates Naj's current private link) ... ");
    execFileSync("npx", ["wrangler", "secret", "put", "RESIDENTS_KEY", "--name", "azimuth-2"], { input: v, stdio: ["pipe", "pipe", "inherit"], shell: true });
    console.log("ok");
    process.stdout.write("setting NAJMA_RESIDENTS_KEY for this user ... ");
    execFileSync("setx", ["NAJMA_RESIDENTS_KEY", v], { stdio: ["pipe", "pipe", "inherit"] });
    console.log("ok");
    let ck = "";
    try { const winreg = require("child_process").execFileSync("reg", ["query", "HKCU\\Environment", "/v", "NAJMA_CLIENT_KEY"], { encoding: "utf8" }); ck = (winreg.match(/REG_SZ\s+(\S+)/) || [])[1] || ""; } catch (e) {}
    console.log("\nNaj's NEW private link (send her this; her old one no longer opens):");
    console.log("  https://azimuth-2.digitalchemy.workers.dev/map?key=" + (ck || "<CLIENT_KEY>") + "&rk=" + v);
    console.log("\nThe residents page itself: https://azimuth-2.digitalchemy.workers.dev/residents?rk=" + v);
    // GUARD 2 - the Azimuth Rings session is sole deployer and checks "live matches my tree" before every
    // deploy. A secret change it does not know about is a live version it does not know about.
    const stamp = new Date().toISOString();
    require("fs").appendFileSync("C:\Dev\naj-market-pulse\data\demo\_secret_changes.log", stamp + "  RESIDENTS_KEY rotated on azimuth-2 by set_residents_key.js --new (a new worker version was uploaded)\n");
    console.log("\nNOTIFY THE AZIMUTH RINGS SESSION: RESIDENTS_KEY was rotated at " + stamp + " - this uploaded a new version of azimuth-2. Logged in data/demo/_secret_changes.log.");
  } catch (e) { console.error("\nfailed: " + e.message); process.exit(1); }
  process.exit(0);
}
const { execFileSync } = require("child_process");
const readline = require("readline");

function ask(question) {
  return new Promise((resolve) => {
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout, terminal: true });
    const onData = (ch) => {                     // echo off: show nothing at all while it is typed
      const s = String(ch);
      if (s === "\r" || s === "\n" || s === "") process.stdin.removeListener("data", onData);
      else process.stdout.write("");
    };
    process.stdin.on("data", onData);
    rl.question(question, (answer) => { rl.close(); process.stdout.write("\n"); resolve(answer.trim()); });
    rl._writeToOutput = () => {};
  });
}

(async () => {
  const v = await ask("Paste the RESIDENTS_KEY value (it will not be shown), then Enter: ");
  if (!v) { console.error("nothing entered - nothing changed."); process.exit(1); }
  if (v.startsWith("<") && v.endsWith(">")) {
    console.error("that looks like a placeholder, not a key - nothing changed.");
    process.exit(1);
  }
  if (v.length < 12) {
    console.error("that is " + v.length + " characters; the worker ignores anything under 12 - nothing changed.");
    process.exit(1);
  }
  try {
    execFileSync("setx", ["NAJMA_RESIDENTS_KEY", v], { stdio: ["pipe", "pipe", "inherit"] });
    console.log("NAJMA_RESIDENTS_KEY set to a " + v.length + "-character value. It was not printed.");
    console.log("Read from HKCU\\Environment, so it works right away - no restart.");
  } catch (e) {
    console.error("failed: " + e.message + "\nNothing was printed, so no value leaked.");
    process.exit(1);
  }
})();
