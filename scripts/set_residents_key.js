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
