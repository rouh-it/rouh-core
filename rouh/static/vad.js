// Silero: deciding whether a sound is speech, rather than whether it is loud.
//
// The detector this replaces asked "is this louder than the room". That is the
// wrong question, and it was measured being wrong: a tumbling dryer recorded at
// 0.126 RMS against speech at 0.093, so the dryer was the louder of the two and
// opened the microphone every few seconds. Silero scored the same dryer at 0.02
// and the same speech at 0.91. It is a small trained model that answers the
// question we actually have.
//
// It runs here in the browser rather than on the server, so no audio leaves the
// machine until there is something worth sending. Roughly five megabytes over
// the wire the first time and cached for ever after, because the asset paths
// carry a hash of their contents.
//
// The page never waits for it. Until this is ready the old loudness detector is
// in charge, and everything keeps working if it never loads at all.

const SAMPLE_RATE = 16000;
const FRAME = 512;          // what the v5 model expects at 16 kHz, about 32 ms

let session = null;
let state = null;
let ort = null;
let busy = false;

export const frameSize = FRAME;

export async function load() {
  if (session) return true;
  ort = await import("./ort.min.mjs");
  // Threads need SharedArrayBuffer, which needs cross-origin isolation headers
  // this page does not send. One thread is plenty: a frame takes about a
  // millisecond and they arrive every thirty-two.
  ort.env.wasm.numThreads = 1;
  ort.env.wasm.simd = true;
  // Each file by its own address rather than a folder to look in: every file
  // is served under a hash of its own content (rouh/web/assets.py), so the
  // runtime's two files are not in this one's folder. Both names are
  // rewritten to their hashed addresses as this file is served.
  ort.env.wasm.wasmPaths = {
    mjs: new URL("./ort-wasm-simd-threaded.mjs", import.meta.url).href,
    wasm: new URL("./ort-wasm-simd-threaded.wasm", import.meta.url).href,
  };
  ort.env.logLevel = "error";
  session = await ort.InferenceSession.create(
    new URL("./silero-vad.onnx", import.meta.url).href,
    { executionProviders: ["wasm"], graphOptimizationLevel: "all" }
  );
  reset();
  return true;
}

export function reset() {
  if (!ort) return;
  // The model carries its own memory of what it has heard. Clearing it between
  // sessions stops one conversation's tail biasing the next one's opening word.
  state = new ort.Tensor("float32", new Float32Array(2 * 1 * 128), [2, 1, 128]);
}

export function ready() {
  return session !== null;
}

/**
 * @param {Float32Array} frame exactly FRAME samples, -1..1
 * @returns {Promise<number|null>} probability this is speech, or null if a run
 *   is already in flight - dropping a frame is better than queueing behind one.
 */
export async function probability(frame) {
  if (!session || busy) return null;
  busy = true;
  try {
    const out = await session.run({
      input: new ort.Tensor("float32", frame, [1, frame.length]),
      state: state,
      sr: new ort.Tensor("int64", BigInt64Array.from([BigInt(SAMPLE_RATE)]), []),
    });
    state = out.stateN;
    return out.output.data[0];
  } finally {
    busy = false;
  }
}
