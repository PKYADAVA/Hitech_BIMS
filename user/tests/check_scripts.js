/* Syntax-check many scripts in one node process.
 *
 * Used by user/tests/test_template_scripts.py. Spawning `node --check` once
 * per template cost four minutes on Windows, almost all of it node starting
 * up — the checking itself is instant. So the readings are handed over in one
 * go on stdin and answered in one go on stdout.
 *
 * Input   {"<name>": ["<reading>", "<reading>", ...], ...}
 * Output  ["<name>", ...]   names where EVERY reading failed to parse
 *
 * Every reading, because a template's script is not valid JavaScript until it
 * is rendered and there is more than one thing it might render to — see the
 * module docstring on the Python side. One that parses is enough.
 */
const vm = require("vm");

function parses(source) {
  try {
    // A syntax check, not an execution: compileFunction throws SyntaxError on
    // malformed source and does not run a line of it.
    vm.compileFunction(source);
    return true;
  } catch (e) {
    // Anything that is not a syntax error (a reference to something undefined,
    // say) is not this check's business — compileFunction does not evaluate,
    // so in practice only SyntaxError arrives here.
    return !(e instanceof SyntaxError);
  }
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { raw += chunk; });
process.stdin.on("end", () => {
  const groups = JSON.parse(raw);
  const broken = Object.keys(groups).filter(
    (name) => !groups[name].some(parses)
  );
  process.stdout.write(JSON.stringify(broken));
});
