/*
 * Microphone capture processor.
 *
 * Runs on the audio thread. Takes whatever rate the browser opened the input at
 * (usually 48000 Hz), low-passes it so decimation does not fold high frequencies
 * back into the speech band, resamples to 16000 Hz, and posts one message per
 * 20 ms of audio: 320 samples of signed 16-bit PCM plus the RMS of that frame.
 *
 * It always posts, whether or not anyone is talking. The main thread runs the
 * voice detector and decides what to put on the wire, because it also needs the
 * frames that came just before speech started.
 */

class MicProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const o = (options && options.processorOptions) || {};
    this.targetRate = o.targetRate || 16000;
    this.frameSamples = o.frameSamples || 320; // 20 ms at 16 kHz
    this.inRate = sampleRate; // provided by the AudioWorkletGlobalScope
    this.step = this.inRate / this.targetRate;

    this.tail = new Float32Array(0); // filtered input not yet consumed
    this.pos = 0; // fractional read cursor into `tail`

    this.out = new Int16Array(this.frameSamples);
    this.outLen = 0;
    this.sumSq = 0;
    this.sumN = 0;

    this.z1 = 0;
    this.z2 = 0;
    this.setLowpass(Math.min(7000, this.targetRate * 0.45));

    this.running = true;
    this.port.onmessage = (e) => {
      if (e && e.data === 'stop') this.running = false;
    };
  }

  // Second order Butterworth low pass, transposed direct form II.
  setLowpass(fc) {
    const w0 = (2 * Math.PI * fc) / this.inRate;
    const cs = Math.cos(w0);
    const sn = Math.sin(w0);
    const alpha = sn / (2 * 0.70710678);
    const a0 = 1 + alpha;
    this.b0 = ((1 - cs) / 2) / a0;
    this.b1 = (1 - cs) / a0;
    this.b2 = ((1 - cs) / 2) / a0;
    this.a1 = (-2 * cs) / a0;
    this.a2 = (1 - alpha) / a0;
  }

  filter(x) {
    const y = this.b0 * x + this.z1;
    this.z1 = this.b1 * x - this.a1 * y + this.z2;
    this.z2 = this.b2 * x - this.a2 * y;
    return y;
  }

  emit() {
    const pcm = this.out;
    const rms = this.sumN ? Math.sqrt(this.sumSq / this.sumN) : 0;
    this.out = new Int16Array(this.frameSamples);
    this.outLen = 0;
    this.sumSq = 0;
    this.sumN = 0;
    this.port.postMessage({ pcm: pcm.buffer, rms: rms }, [pcm.buffer]);
  }

  process(inputs) {
    if (!this.running) return false;
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const ch = input[0];
    if (!ch || ch.length === 0) return true;

    const prev = this.tail.length;
    const cat = new Float32Array(prev + ch.length);
    cat.set(this.tail, 0);
    for (let i = 0; i < ch.length; i++) cat[prev + i] = this.filter(ch[i]);

    let p = this.pos;
    const last = cat.length - 1;
    while (p < last) {
      const i0 = p | 0;
      const frac = p - i0;
      const s = cat[i0] * (1 - frac) + cat[i0 + 1] * frac;
      const c = s > 1 ? 1 : s < -1 ? -1 : s;
      this.out[this.outLen++] = c < 0 ? c * 0x8000 : c * 0x7fff;
      this.sumSq += c * c;
      this.sumN++;
      if (this.outLen === this.frameSamples) this.emit();
      p += this.step;
    }

    const keep = p | 0;
    this.tail = cat.subarray(keep).slice();
    this.pos = p - keep;
    return true;
  }
}

registerProcessor('mic-processor', MicProcessor);
