/**
 * mix — lay audio tracks over a video: its own sound, a voice-over, music.
 *
 * Per track: volume, delay, fade in and out. A track marked `duck` is pushed
 * down under the `role: "voice"` track automatically (sidechaincompress), so
 * nobody has to draw a volume curve by hand.
 *
 * The video decides the length: the mix is padded with silence or cut to
 * exactly the length of the source. (factory used amix duration=first plus
 * -shortest, which cut the video short whenever the first leg was a voice
 * shorter than the clip.)
 */

import { BadRequest } from '../errors.js'
import { VIDEO_EXT, resolveInput, resolveOutput } from '../paths.js'
import { A, V, list, num, oneOf, optNum } from './common.js'

const COPYABLE_VIDEO = ['h264', 'hevc', 'av1', 'vp9', 'mpeg4']

async function parseMix(body, prefix = '') {
  const tracksIn = list(body.tracks, `${prefix}tracks`, { max: 16 })
  const keepOriginal = body.keep_original_audio !== false
  const originalVolume = num(body.original_volume ?? 1, `${prefix}original_volume`, { min: 0, max: 4 })
  if (!tracksIn.length && keepOriginal) {
    throw new BadRequest(`nothing to mix: pass ${prefix}tracks or set ${prefix}keep_original_audio=false`)
  }
  const tracks = []
  for (const [i, t] of tracksIn.entries()) {
    const f = `${prefix}tracks[${i}]`
    if (!t || typeof t !== 'object') throw new BadRequest(`${f} must be an object`)
    tracks.push({
      input: await resolveInput(t.input, `${f}.input`),
      volume: num(t.volume ?? 1, `${f}.volume`, { min: 0, max: 4 }),
      delay: num(t.delay ?? 0, `${f}.delay`, { min: 0, max: 86_400 }),
      fadeIn: optNum(t.fade_in, `${f}.fade_in`, { min: 0, max: 60 }),
      fadeOut: optNum(t.fade_out, `${f}.fade_out`, { min: 0, max: 60 }),
      fadeOutAt: optNum(t.fade_out_at, `${f}.fade_out_at`, { min: 0, max: 86_400 }),
      role: oneOf(t.role, ['voice', 'music', 'sfx'], `${f}.role`, null),
      duck: Boolean(t.duck),
      duckThreshold: num(t.duck_threshold ?? 0.03, `${f}.duck_threshold`, { min: 0.001, max: 1 }),
      duckRatio: num(t.duck_ratio ?? 8, `${f}.duck_ratio`, { min: 1, max: 20 }),
    })
  }
  const voiceIdx = tracks.findIndex((t) => t.role === 'voice')
  if (tracks.some((t) => t.duck) && voiceIdx === -1) throw new BadRequest('duck requires a track with role="voice"')
  if (tracks.filter((t) => t.role === 'voice').length > 1) throw new BadRequest('only one track can have role="voice"')
  if (voiceIdx !== -1 && tracks[voiceIdx].duck) throw new BadRequest('the voice track cannot duck under itself')
  return { tracks, keepOriginal, originalVolume }
}

export async function mixCore(ws, src, step) {
  const meta = await ws.probe(src)
  const length = meta.duration
  const out = ws.name('mix', '.mp4')
  const videoArgs = meta.has_video
    ? ['-map', '0:v:0', ...(COPYABLE_VIDEO.includes(meta.video_codec) ? ['-c:v', 'copy'] : V)]
    : ['-vn']

  const args = ['-i', src]
  for (const t of step.tracks) args.push('-i', await ws.link(t.input, 'track'))

  const steps = []
  const legs = []
  if (step.keepOriginal && meta.has_audio) {
    steps.push(`[0:a]aresample=48000,aformat=channel_layouts=stereo,volume=${step.originalVolume}[m0]`)
    legs.push('[m0]')
  }

  for (const [i, t] of step.tracks.entries()) {
    const chain = ['aresample=48000', 'aformat=channel_layouts=stereo', `volume=${t.volume}`]
    if (t.delay > 0) chain.push(`adelay=${Math.round(t.delay * 1000)}:all=1`)
    if (t.fadeIn) chain.push(`afade=t=in:st=${t.delay}:d=${t.fadeIn}`)
    if (t.fadeOut) {
      const at = t.fadeOutAt ?? Math.max(0, Number((length - t.fadeOut).toFixed(3)))
      chain.push(`afade=t=out:st=${at}:d=${t.fadeOut}`)
    }
    steps.push(`[${i + 1}:a]${chain.join(',')}[t${i}]`)
  }

  const voiceIdx = step.tracks.findIndex((t) => t.role === 'voice')
  const ducked = step.tracks.filter((t) => t.duck).length
  if (ducked) {
    // The voice is both a leg of the mix and the key that ducks the music. The
    // key copy is padded with silence: sidechaincompress stops when its key
    // ends, and music should not stop when the voice does.
    const keys = Array.from({ length: ducked }, (_, k) => `[sc${k}]`).join('')
    steps.push(`[t${voiceIdx}]asplit=${ducked + 1}[voice]${keys}`)
  }

  let k = 0
  for (const [i, t] of step.tracks.entries()) {
    if (ducked && i === voiceIdx) {
      legs.push('[voice]')
      continue
    }
    if (t.duck) {
      steps.push(`[sc${k}]apad[key${k}]`)
      steps.push(`[t${i}][key${k}]sidechaincompress=threshold=${t.duckThreshold}:ratio=${t.duckRatio}:attack=20:release=300[d${i}]`)
      legs.push(`[d${i}]`)
      k += 1
      continue
    }
    legs.push(`[t${i}]`)
  }

  if (!legs.length) {
    // Everything muted: strip the audio rather than build an empty mixer.
    await ws.ffmpeg(['-i', src, ...videoArgs, '-an', out], { duration: length })
    return out
  }

  // normalize=0 keeps the volumes the caller asked for; amix otherwise divides
  // everything by the number of inputs the moment a second track joins.
  const mixed = legs.length === 1
    ? `${legs[0]}anull[mx]`
    : `${legs.join('')}amix=inputs=${legs.length}:duration=longest:dropout_transition=0:normalize=0[mx]`
  steps.push(mixed)
  const fit = length > 0 ? `[mx]apad,atrim=end=${length}[aout]` : '[mx]anull[aout]'
  steps.push(fit)

  args.push('-filter_complex', steps.join(';'), ...videoArgs, '-map', '[aout]', ...A)
  if (!(length > 0)) args.push('-shortest')
  args.push(out)
  await ws.ffmpeg(args, { duration: length })
  return out
}

export default {
  name: 'mix',

  parseStep: parseMix,
  core: mixCore,

  async validate(body) {
    const step = await parseMix(body)
    const input = await resolveInput(body.input, 'input')
    const output = await resolveOutput(body.output, 'output', VIDEO_EXT)
    return { input, output, step }
  },

  async run({ input, output, step }, ws) {
    const src = await ws.link(input)
    const out = await mixCore(ws, src, step)
    const meta = await ws.probe(out)
    await ws.publish(out, output.abs)
    return { output: output.rel, meta }
  },
}
