// Compile contracts -> build/<Name>.json { abi, bytecode }
// EVM target: paris (no PUSH0) for max chain compatibility.
const solc = require("solc");
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const sources = {};
for (const f of fs.readdirSync(path.join(root, "contracts"))) {
  if (f.endsWith(".sol")) {
    sources[f] = { content: fs.readFileSync(path.join(root, "contracts", f), "utf8") };
  }
}

const input = {
  language: "Solidity",
  sources,
  settings: {
    evmVersion: "paris",
    optimizer: { enabled: true, runs: 200 },
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object"] } },
  },
};

const out = JSON.parse(solc.compile(JSON.stringify(input)));
const errors = (out.errors || []).filter((e) => e.severity === "error");
if (errors.length) {
  console.error(errors.map((e) => e.formattedMessage).join("\n"));
  process.exit(1);
}
(out.errors || []).forEach((e) => console.warn(e.formattedMessage));

fs.mkdirSync(path.join(root, "build"), { recursive: true });
for (const file of Object.keys(out.contracts)) {
  for (const name of Object.keys(out.contracts[file])) {
    const c = out.contracts[file][name];
    fs.writeFileSync(
      path.join(root, "build", `${name}.json`),
      JSON.stringify({ abi: c.abi, bytecode: "0x" + c.evm.bytecode.object }, null, 2)
    );
    console.log(`built ${name} (${c.evm.bytecode.object.length / 2} bytes)`);
  }
}
