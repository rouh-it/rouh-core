/* The speech detector's interface (vad.js beside this file), for the type
 * checker (tools/typecheck). It stands in for vad.js so the checker reads the
 * five names app/voice.js uses rather than the minified ONNX runtime vad.js
 * imports. Never loaded by a browser. */

/** Samples in one frame the detector reads: 512 at 16 kHz, 32 ms. */
export const frameSize: number;
/** Fetch the runtime and the model, once. True when the detector is ready. */
export function load(): Promise<boolean>;
/** Forget what the detector has heard, between utterances. */
export function reset(): void;
/** Whether `load` has finished. */
export function ready(): boolean;
/** How likely one frame of 16 kHz samples is speech, 0 to 1, or null when a
 *  frame is already being read and this one is dropped. */
export function probability(frame: Float32Array): Promise<number | null>;
