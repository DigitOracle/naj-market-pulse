/* Set CLIENT_KEY on azimuth-2 and NAJMA_CLIENT_KEY on this machine, to the same value, in one go.
 *
 * The value is generated here and never printed, never typed, never pasted - so the two cannot
 * drift apart, which is exactly what went wrong the first time round.
 *
 * CLIENT_KEY opens only the app pages (CLIENT_PATHS in the worker) - not the board, inbox, outbox,
 * ledger, or anything that messages a contact or spends model time. That is READ_KEY, which must
 * never go near a link that appears on camera.
 *
 * Safe to re-run: it overwrites CLIENT_KEY, so any client link already carrying the OLD client
 * value stops working. Nothing carries it yet (the key was first set on 17 Sep 2026), but once real
 * client links are out there, add a value to the comma-separated list by hand instead of re-running
 * this - the worker keeps every value in CLIENT_KEY alive and puts the first one into new links.
 *
 *   node scripts/set_client_key.js
 */
"use strict";
const { execFileSync } = require("child_process");
const crypto = require("crypto");

const WORKER = "azimuth-2";
const value = crypto.randomBytes(24).toString("base64url");   // 32 chars, url-safe, well over the worker's 12-char floor

function run(cmd, args, opts) {
  return execFileSync(cmd, args, Object.assign({ stdio: ["pipe", "pipe", "inherit"] }, opts));
}

try {
  process.stdout.write("setting CLIENT_KEY on " + WORKER + " ... ");
  run("npx", ["wrangler", "secret", "put", "CLIENT_KEY", "--name", WORKER], { input: value, shell: true });
  console.log("ok");

  process.stdout.write("setting NAJMA_CLIENT_KEY for this user ... ");
  run("setx", ["NAJMA_CLIENT_KEY", value], { shell: true });
  console.log("ok");

  console.log("\nboth set to the same " + value.length + "-character value. It was not printed.");
  console.log("The capture script reads it from HKCU\\Environment, so it works right away -");
  console.log("no restart. Verify with:  python scripts/demo_capture.py probe");
} catch (e) {
  console.error("\nfailed: " + e.message);
  console.error("Nothing was printed, so no value leaked. Fix the error above and re-run.");
  process.exit(1);
}
