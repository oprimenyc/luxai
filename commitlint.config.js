/** @type {import('@commitlint/types').UserConfig} */
const config = {
  // Accept any commit message format — no conventional commit enforcement.
  ignores: [() => true],
};

export default config;
