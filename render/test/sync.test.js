/**
 * The inline routes (probe, frame, match), health, and how errors come back.
 */

import assert from 'node:assert/strict'
import fsp from 'node:fs/promises'
import { after, before, describe, test } from 'node:test'

import { getJob, near, post, runJob, setup } from './helpers.js'

let t

before(async () => {
  t = await setup('sync', { fixtures: ['sample.mp4', 'silent.mp4', 'voice.mp3', 'scene-a.mp4', 'scene-b.mp4', 'anchor.png'] })
  await fsp.writeFile(t.abs('files/fx/broken.mp4'), Buffer.from('this is not a video file at all, just bytes'.repeat(20)))
  await fsp.writeFile(t.abs('secrets/google-key.json'), '{"private_key":"x"}')
})

after(() => t.stop())

describe('health', () => {
  test('reports ffmpeg, version and the queue', async () => {
    const res = await fetch(`${t.base}/health`)
    assert.equal(res.status, 200)
    const body = await res.json()
    assert.equal(body.ok, true)
    assert.equal(typeof body.version, 'string')
    assert.match(body.ffmpeg, /\d/)
    assert.deepEqual(Object.keys(body.queue).sort(), ['queued', 'running'])
  })
})

describe('probe', () => {
  test('a video with sound', async () => {
    const { status, json } = await post(t.base, '/probe', { input: 'files/fx/sample.mp4' })
    assert.equal(status, 200, JSON.stringify(json))
    assert.ok(near(json.duration, 4, 0.1), `duration ${json.duration}`)
    assert.equal(json.width, 320)
    assert.equal(json.height, 240)
    assert.equal(json.display_width, 320)
    assert.equal(json.fps, 25)
    assert.equal(json.video_codec, 'h264')
    assert.equal(json.has_audio, true)
    assert.equal(json.audio_codec, 'aac')
    assert.ok(json.size_bytes > 0)
  })

  test('a video without sound', async () => {
    const { json } = await post(t.base, '/probe', { input: 'files/fx/silent.mp4' })
    assert.equal(json.has_video, true)
    assert.equal(json.has_audio, false)
    assert.equal(json.width, 480)
  })

  test('an audio file', async () => {
    const { json } = await post(t.base, '/probe', { input: 'files/fx/voice.mp3' })
    assert.equal(json.has_video, false)
    assert.equal(json.has_audio, true)
    assert.equal(json.width, null)
    assert.ok(near(json.duration, 6, 0.2), `duration ${json.duration}`)
  })
})

describe('frame', () => {
  test('a JPEG at a given second', async () => {
    const { status, json } = await post(t.base, '/frame', { input: 'files/fx/sample.mp4', output: 'files/out/frame-2.jpg', at: 2 })
    assert.equal(status, 200, JSON.stringify(json))
    assert.equal(json.output, 'files/out/frame-2.jpg')
    assert.equal(json.width, 320)
    assert.equal(json.height, 240)
    const head = (await fsp.readFile(t.abs('files/out/frame-2.jpg'))).subarray(0, 2).toString('hex')
    assert.equal(head, 'ffd8')
  })

  test('the last frame', async () => {
    const { json } = await post(t.base, '/frame', { input: 'files/fx/sample.mp4', output: 'files/out/last.jpg', at: 'last' })
    assert.ok(near(json.at, 3.96, 0.05), `at ${json.at}`)
  })

  test('scaled down to max_width', async () => {
    const { json } = await post(t.base, '/frame', { input: 'files/fx/sample.mp4', output: 'cache/thumbs/small.jpg', max_width: 160 })
    assert.equal(json.width, 160)
    assert.equal(json.height, 120)
  })
})

describe('match', () => {
  test('finds the shared still in the tail of the outgoing scene', async () => {
    const { status, json } = await post(t.base, '/match', { input: 'files/fx/scene-a.mp4', image: 'files/fx/anchor.png', window: 'tail' })
    assert.equal(status, 200, JSON.stringify(json))
    assert.ok(near(json.at, 3.0, 0.02), `at ${json.at}`)
    assert.ok(json.score > 0.95, `score ${json.score}`)
    assert.equal(json.window, 'tail')
    assert.ok(json.frames > 10)
  })

  test('finds it in the head of the incoming scene', async () => {
    const { json } = await post(t.base, '/match', { input: 'files/fx/scene-b.mp4', image: 'files/fx/anchor.png', window: 'head' })
    assert.ok(near(json.at, 0.52, 0.02), `at ${json.at}`)
    assert.ok(json.score > 0.95, `score ${json.score}`)
  })

  test('only looks inside the window', async () => {
    const { json } = await post(t.base, '/match', { input: 'files/fx/scene-a.mp4', image: 'files/fx/anchor.png', window: 'head', seconds: 2 })
    assert.equal(json.window_start, 0)
    assert.ok(json.at < 2, `at ${json.at}`)
  })

  test('a missing still is a 404', async () => {
    const { status, json } = await post(t.base, '/match', { input: 'files/fx/scene-a.mp4', image: 'files/fx/gone.png' })
    assert.equal(status, 404)
    assert.equal(json.error.code, 'not_found')
  })
})

describe('errors', () => {
  test('a missing input is 404 not_found', async () => {
    const { status, json } = await post(t.base, '/probe', { input: 'files/fx/nope.mp4' })
    assert.equal(status, 404)
    assert.equal(json.error.code, 'not_found')
    assert.match(json.error.message, /not found/)
    assert.equal(json.error.stderr_tail, null)
  })

  for (const input of ['/etc/passwd', '../x.mp4', 'files/../../x.mp4', 'secrets/google-key.json']) {
    test(`${input} is refused with 400`, async () => {
      const { status, json } = await post(t.base, '/probe', { input })
      assert.equal(status, 400)
      assert.equal(json.error.code, 'bad_request')
    })
  }

  test('a queued op is validated before it is queued', async () => {
    const { status, json } = await post(t.base, '/trim', { input: 'files/fx/nope.mp4', output: 'files/out/x.mp4' })
    assert.equal(status, 404)
    assert.equal(json.error.code, 'not_found')
    const bad = await post(t.base, '/trim', { input: 'files/fx/sample.mp4', output: 'secrets/x.mp4' })
    assert.equal(bad.status, 400)
  })

  test('unknown routes and jobs are 404, wrong methods 405', async () => {
    assert.equal((await post(t.base, '/explode', {})).status, 404)
    assert.equal((await getJob(t.base, 'no-such-job')).status, 404)
    const del = await fetch(`${t.base}/jobs/no-such-job`, { method: 'DELETE' })
    assert.equal(del.status, 404)
    const get = await fetch(`${t.base}/trim`)
    assert.equal(get.status, 405)
    assert.equal((await get.json()).error.code, 'method_not_allowed')
  })

  test('a body that is not JSON is 400', async () => {
    const { status, json } = await post(t.base, '/probe', null, { raw: '{"input": ' })
    assert.equal(status, 400)
    assert.match(json.error.message, /not valid JSON/)
    const arr = await post(t.base, '/probe', null, { raw: '[1,2]' })
    assert.equal(arr.status, 400)
  })

  test('a file ffmpeg cannot read is 500 ffmpeg_failed with the end of stderr', async () => {
    const { status, json } = await post(t.base, '/probe', { input: 'files/fx/broken.mp4' })
    assert.equal(status, 500)
    assert.equal(json.error.code, 'ffmpeg_failed')
    assert.equal(typeof json.error.stderr_tail, 'string')
    assert.ok(json.error.stderr_tail.length > 0 && json.error.stderr_tail.length <= 2000)
  })

  test('the same file in a job ends the job with ffmpeg_failed', async () => {
    const job = await runJob(t.base, 'trim', { input: 'files/fx/broken.mp4', output: 'files/out/broken.mp4', start: 0, end: 1 })
    assert.equal(job.status, 'error')
    assert.equal(job.error.code, 'ffmpeg_failed')
    assert.ok(job.error.stderr_tail)
    await assert.rejects(fsp.stat(t.abs('files/out/broken.mp4')), /ENOENT/)
  })
})

describe('X-Batch-Id', () => {
  test('is echoed back, tamed', async () => {
    const { headers } = await post(t.base, '/probe', { input: 'files/fx/sample.mp4' }, { batchId: 'clip 42/<x>' })
    assert.equal(headers.get('x-batch-id'), 'clip_42__x_')
  })

  test('is kept on the job', async () => {
    const job = await runJob(t.base, 'trim', { input: 'files/fx/sample.mp4', output: 'files/out/batch.mp4', start: 0, end: 1 })
    assert.equal(job.status, 'done', JSON.stringify(job.error))
    assert.equal(job.batch_id, 'test-batch')
    assert.equal(job.progress, 1)
    assert.equal(job.op, 'trim')
    assert.ok(job.created_at && job.started_at && job.finished_at)
  })
})
