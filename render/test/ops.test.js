/**
 * The queued operations, end to end: submit over HTTP, wait for the job, then
 * look at the file it left on the volume.
 */

import assert from 'node:assert/strict'
import fsp from 'node:fs/promises'
import { after, before, describe, test } from 'node:test'

import { ASS, ass, changedPixels, grayFrame, near, post, probe, runJob, setup, waitJob, why } from './helpers.js'

let t

const SAMPLE = 'files/fx/sample.mp4'
const SILENT = 'files/fx/silent.mp4'

/** Run an op that must succeed; returns the job result. */
async function ok(op, body) {
  const job = await runJob(t.base, op, body)
  assert.equal(job.status, 'done', `${op} failed: ${why(job)}`)
  return job.result
}

/** Submit an op that must be refused up front. */
async function refused(op, body, status, re) {
  const res = await post(t.base, `/${op}`, body)
  assert.equal(res.status, status, JSON.stringify(res.json))
  if (re) assert.match(res.json.error.message, re)
  return res.json
}

before(async () => {
  t = await setup('ops')
})

after(() => t.stop())

describe('preview', () => {
  test('poster, animated preview and a thumbnail in one job', async () => {
    const r = await ok('preview', {
      input: SAMPLE,
      poster_output: 'files/out/poster.jpg',
      preview_output: 'files/out/preview.webp',
      thumbs: [{ width: 160, output: 'cache/thumbs/sample-160.jpg' }],
    })
    // 720 asked, 320 available: never upscaled.
    assert.equal(r.poster.width, 320)
    assert.equal(r.poster.output, 'files/out/poster.jpg')
    assert.equal(r.thumbs[0].width, 160)
    assert.equal(r.preview.segments, 4)
    assert.equal(r.preview.width, 320)
    assert.equal(r.source.width, 320)

    const webp = await fsp.readFile(t.abs('files/out/preview.webp'))
    assert.equal(webp.toString('ascii', 0, 4), 'RIFF')
    assert.equal(webp.toString('ascii', 8, 12), 'WEBP')
    assert.ok(webp.includes(Buffer.from('ANIM')), 'preview is not animated')
    assert.ok(webp.length < 500_000, `preview is ${webp.length} bytes`)
    const thumb = await fsp.readFile(t.abs('cache/thumbs/sample-160.jpg'))
    assert.equal(thumb.subarray(0, 2).toString('hex'), 'ffd8')
  })

  test('needs at least one output', async () => {
    await refused('preview', { input: SAMPLE }, 400, /at least one of/)
  })
})

describe('trim', () => {
  test('keeps the range, with sound', async () => {
    const r = await ok('trim', { input: SAMPLE, output: 'files/out/trim.mp4', start: 1, end: 3 })
    assert.equal(r.output, 'files/out/trim.mp4')
    assert.ok(near(r.meta.duration, 2, 0.1), `duration ${r.meta.duration}`)
    assert.equal(r.meta.has_audio, true)
    assert.equal(r.meta.video_codec, 'h264')
  })

  test('an empty range is refused before queueing', async () => {
    await refused('trim', { input: SAMPLE, output: 'files/out/x.mp4', start: 3, end: 2 }, 400, /greater than/)
  })
})

describe('split', () => {
  test('cuts into consecutive pieces', async () => {
    const r = await ok('split', {
      input: SAMPLE,
      at: [1.5, 3],
      outputs: ['files/out/part-1.mp4', 'files/out/part-2.mp4', 'files/out/part-3.mp4'],
    })
    assert.equal(r.outputs.length, 3)
    const lengths = r.outputs.map((o) => o.meta.duration)
    assert.ok(near(lengths[0], 1.5, 0.1) && near(lengths[1], 1.5, 0.1) && near(lengths[2], 1, 0.1), lengths.join(', '))
  })

  test('needs one more output than cut points', async () => {
    await refused('split', { input: SAMPLE, at: [1], outputs: ['files/out/a.mp4'] }, 400, /2 entries/)
  })
})

describe('crop', () => {
  test('landscape to portrait, cover', async () => {
    const r = await ok('crop', { input: SAMPLE, output: 'files/out/crop-cover.mp4', width: 270, height: 480 })
    assert.equal(r.meta.width, 270)
    assert.equal(r.meta.height, 480)
    assert.equal(r.meta.has_audio, true)
  })

  test('blurred background', async () => {
    const r = await ok('crop', { input: SAMPLE, output: 'files/out/crop-blur.mp4', width: 270, height: 480, mode: 'blur' })
    assert.equal(r.meta.width, 270)
    assert.ok(near(r.meta.duration, 4, 0.1))
  })

  test('a silent source stays silent', async () => {
    const r = await ok('crop', { input: SILENT, output: 'files/out/crop-silent.mp4', width: 240, height: 240, mode: 'pad' })
    assert.equal(r.meta.width, 240)
    assert.equal(r.meta.has_audio, false)
  })

  test('needs a target', async () => {
    await refused('crop', { input: SAMPLE, output: 'files/out/x.mp4' }, 400, /needs aspect/)
  })
})

describe('burn', () => {
  test('a logo and subtitles, sound kept', async () => {
    const r = await ok('burn', {
      input: SAMPLE,
      output: 'files/out/burn.mp4',
      overlays: [{ image: 'files/fx/overlay.png', x: 10, y: 10, width: 48, opacity: 0.8, start: 0.5, end: 3 }],
      subtitles_ass: ASS,
    })
    assert.equal(r.meta.width, 320)
    assert.ok(near(r.meta.duration, 4, 0.1))
    assert.equal(r.meta.has_audio, true)
  })

  test('nothing to burn is refused before queueing', async () => {
    await refused('burn', { input: SAMPLE, output: 'files/out/x.mp4' }, 400, /nothing to burn/)
  })

  // With a font that lacks Cyrillic, libass draws the same empty box for every
  // letter, so two different words would come out identical.
  for (const font of ['DejaVu Sans', 'Arial']) {
    test(`Cyrillic subtitles render real letters (${font})`, async () => {
      const zhe = await ok('burn', { input: 'files/fx/plain.mp4', output: `files/out/zhe-${font}.mp4`, subtitles_ass: ass('ЖЖЖЖЖЖ', { font, size: 40 }) })
      const pe = await ok('burn', { input: 'files/fx/plain.mp4', output: `files/out/pe-${font}.mp4`, subtitles_ass: ass('ПППППП', { font, size: 40 }) })
      const plain = await grayFrame(t.abs('files/fx/plain.mp4'), 1)
      const a = await grayFrame(t.abs(zhe.output), 1)
      const b = await grayFrame(t.abs(pe.output), 1)
      assert.ok(changedPixels(plain, a) > 500, 'no text was drawn')
      assert.ok(changedPixels(a, b) > 200, `Ж and П look the same (${changedPixels(a, b)} px differ): no Cyrillic glyphs`)
    })
  }
})

describe('mix', () => {
  test('voice over music that ducks under it, cut to the video', async () => {
    const r = await ok('mix', {
      input: SAMPLE,
      output: 'files/out/mix.mp4',
      keep_original_audio: true,
      original_volume: 0.3,
      tracks: [
        { input: 'files/fx/voice.mp3', role: 'voice', delay: 0.5 },
        { input: 'files/fx/long.mp3', role: 'music', volume: 0.5, duck: true, fade_in: 0.5, fade_out: 1 },
      ],
    })
    assert.ok(near(r.meta.duration, 4, 0.3), `duration ${r.meta.duration}`)
    assert.equal(r.meta.has_audio, true)
    assert.equal(r.meta.width, 320)
  })

  test('a silent video gets the music', async () => {
    const r = await ok('mix', { input: SILENT, output: 'files/out/mix-silent.mp4', tracks: [{ input: 'files/fx/long.mp3' }] })
    assert.ok(near(r.meta.duration, 2, 0.3), `duration ${r.meta.duration}`)
    assert.equal(r.meta.has_audio, true)
  })

  test('dropping all sound', async () => {
    const r = await ok('mix', { input: SAMPLE, output: 'files/out/mute.mp4', keep_original_audio: false })
    assert.equal(r.meta.has_audio, false)
  })

  test('ducking needs a voice', async () => {
    await refused('mix', { input: SAMPLE, output: 'files/out/x.mp4', tracks: [{ input: 'files/fx/long.mp3', duck: true }] }, 400, /role="voice"/)
  })

  test('nothing to mix', async () => {
    await refused('mix', { input: SAMPLE, output: 'files/out/x.mp4' }, 400, /nothing to mix/)
  })
})

describe('concat', () => {
  test('different sizes and a silent clip, crossfaded', async () => {
    const r = await ok('concat', { inputs: [SAMPLE, SILENT], output: 'files/out/concat.mp4', width: 240, height: 426, fps: 25 })
    assert.equal(r.meta.width, 240)
    assert.equal(r.meta.height, 426)
    assert.ok(near(r.meta.duration, 5.7, 0.3), `duration ${r.meta.duration}`)
    assert.equal(r.meta.has_audio, true)
    assert.deepEqual(r.joins, [])
  })

  test('takes the first clip\'s size by default', async () => {
    const r = await ok('concat', { inputs: [SAMPLE, SILENT], output: 'files/out/concat-default.mp4' })
    assert.equal(r.meta.width, 320)
    assert.equal(r.meta.height, 240)
    // Both sources are 25 fps; nothing forces 30 on them.
    assert.equal(r.meta.fps, 25)
  })

  test('a dissolve shortens the film by its length', async () => {
    const cut = await ok('concat', { inputs: [SAMPLE, SILENT], output: 'files/out/concat-cut.mp4', transition: 'cut' })
    const fade = await ok('concat', { inputs: [SAMPLE, SILENT], output: 'files/out/concat-fade.mp4', transition_seconds: 0.5 })
    const diff = cut.meta.duration - fade.meta.duration
    assert.ok(near(diff, 0.5, 0.2), `cut ${cut.meta.duration}, crossfade ${fade.meta.duration}`)
  })

  test('align meets the scenes on the shared still', async () => {
    const r = await ok('concat', {
      inputs: ['files/fx/scene-a.mp4', 'files/fx/scene-b.mp4'],
      output: 'files/out/aligned.mp4',
      transition: 'align',
      anchors: ['files/fx/anchor.png'],
    })
    const [join] = r.joins
    assert.equal(join.aligned, true, JSON.stringify(join))
    assert.ok(near(join.out_at, 3.0, 0.02), `out_at ${join.out_at}`)
    assert.ok(near(join.into_at, 0.52, 0.02), `into_at ${join.into_at}`)
    // 3.0 s of the first scene + 1.0 s of the second: the overlap shows once.
    assert.ok(near(r.meta.duration, 4.0, 0.1), `duration ${r.meta.duration}`)
  })

  test('align without a usable still keeps the dissolve and says why', async () => {
    const bare = await ok('concat', {
      inputs: ['files/fx/scene-a.mp4', 'files/fx/scene-b.mp4'],
      output: 'files/out/align-bare.mp4',
      transition: 'align',
    })
    assert.equal(bare.joins[0].reason, 'no still')
    assert.ok(near(bare.meta.duration, 4.74, 0.15), `duration ${bare.meta.duration}`)

    const gone = await ok('concat', {
      inputs: ['files/fx/scene-a.mp4', 'files/fx/scene-b.mp4'],
      output: 'files/out/align-gone.mp4',
      transition: 'align',
      anchors: ['files/fx/deleted.png'],
    })
    assert.equal(gone.joins[0].aligned, false)
    assert.equal(gone.joins[0].reason, 'still not found')
  })

  test('a null anchor is a declared hard cut', async () => {
    const r = await ok('concat', {
      inputs: ['files/fx/scene-a.mp4', 'files/fx/scene-b.mp4'],
      output: 'files/out/align-cut.mp4',
      transition: 'align',
      anchors: [null],
    })
    assert.equal(r.joins[0].reason, 'declared cut')
    assert.ok(near(r.meta.duration, 5.04, 0.15), `duration ${r.meta.duration}`)
  })

  test('needs clips', async () => {
    await refused('concat', { inputs: [], output: 'files/out/x.mp4' }, 400, /at least one clip/)
  })
})

describe('compose', () => {
  test('trim, reframe, burn and mix in one job', async () => {
    const r = await ok('compose', {
      input: SAMPLE,
      output: 'files/out/compose.mp4',
      trim: { start: 0.5, end: 3 },
      crop: { width: 270, height: 480, mode: 'blur' },
      burn: { subtitles_ass: ASS, overlays: [{ image: 'files/fx/overlay.png', x: 4, y: 4 }] },
      mix: { tracks: [{ input: 'files/fx/voice.mp3', role: 'voice' }, { input: 'files/fx/long.mp3', duck: true, volume: 0.4 }] },
    })
    assert.deepEqual(r.steps, ['trim', 'crop', 'burn', 'mix'])
    assert.ok(near(r.meta.duration, 2.5, 0.2), `duration ${r.meta.duration}`)
    assert.equal(r.meta.width, 270)
    assert.equal(r.meta.height, 480)
    assert.equal(r.meta.has_audio, true)
  })

  test('a single step', async () => {
    const r = await ok('compose', { input: SAMPLE, output: 'files/out/compose-burn.mp4', burn: { subtitles_ass: ASS } })
    assert.deepEqual(r.steps, ['burn'])
    assert.equal(r.meta.width, 320)
  })

  test('aligned scenes, then a logo', async () => {
    const r = await ok('compose', {
      output: 'files/out/compose-film.mp4',
      concat: { inputs: ['files/fx/scene-a.mp4', 'files/fx/scene-b.mp4'], transition: 'align', anchors: ['files/fx/anchor.png'] },
      burn: { overlays: [{ image: 'files/fx/overlay.png' }] },
    })
    assert.deepEqual(r.steps, ['concat', 'burn'])
    assert.equal(r.joins[0].aligned, true, JSON.stringify(r.joins))
    assert.ok(near(r.meta.duration, 4.0, 0.1), `duration ${r.meta.duration}`)
  })

  test('leaves no scratch behind', async () => {
    assert.deepEqual(await fsp.readdir(t.abs('cache/render')), [])
  })

  test('refuses what it cannot do', async () => {
    await refused('compose', { input: SAMPLE, output: 'files/out/x.mp4' }, 400, /at least one of/)
    await refused('compose', {
      input: SAMPLE,
      output: 'files/out/x.mp4',
      concat: { inputs: [SAMPLE] },
    }, 400, /not both/)
    await refused('compose', {
      input: SAMPLE,
      output: 'files/out/x.mp4',
      trim: { segments: [{ start: 0, end: 1 }, { start: 2, end: 3 }] },
    }, 400, /single trim range/)
    await refused('compose', { input: SAMPLE, output: 'files/out/x.mp4', burn: {} }, 400, /burn\.overlays/)
  })
})

describe('split-audio', () => {
  test('fixed-length parts for the transcriber', async () => {
    const r = await ok('split-audio', { input: 'files/fx/long.mp3', output_dir: 'cache/tmp/stt-a', chunk_seconds: 25 })
    assert.equal(r.outputs.length, 3)
    assert.deepEqual(r.outputs.map((o) => o.output), ['cache/tmp/stt-a/part-000.mp3', 'cache/tmp/stt-a/part-001.mp3', 'cache/tmp/stt-a/part-002.mp3'])
    assert.ok(near(r.outputs[0].meta.duration, 25, 1), `part 0 is ${r.outputs[0].meta.duration} s`)
    assert.ok(near(r.outputs[1].meta.duration, 25, 1), `part 1 is ${r.outputs[1].meta.duration} s`)
    const third = await probe(t.abs('cache/tmp/stt-a/part-002.mp3'))
    assert.ok(near(third.duration, 20, 1), `part 2 is ${third.duration} s`)
  })

  test('one part when the whole file fits the size limit', async () => {
    const r = await ok('split-audio', { input: SAMPLE, output_dir: 'cache/tmp/stt-b', max_mb: 20 })
    assert.equal(r.outputs.length, 1)
    assert.ok(near(r.outputs[0].meta.duration, 4, 0.3))
  })

  test('a video without sound fails the job as a bad request', async () => {
    const submitted = await post(t.base, '/split-audio', { input: SILENT, output_dir: 'cache/tmp/stt-c' })
    assert.equal(submitted.status, 202)
    const job = await waitJob(t.base, submitted.json.job_id)
    assert.equal(job.status, 'error')
    assert.equal(job.error.code, 'bad_request')
    assert.match(job.error.message, /no audio stream/)
  })
})
