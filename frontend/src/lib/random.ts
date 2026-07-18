// Mulberry32 seeded PRNG — deterministic across reloads so procedurally-
// generated layouts stay stable and only change when we intend them to.
export function mulberry32(seed: number) {
  let t = seed;
  return function () {
    t = (t + 0x6d2b79f5) | 0;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };
}
