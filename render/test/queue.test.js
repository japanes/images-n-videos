/**
 * The job queue: how many run at once, cancelling, expiry, scratch cleanup —
 * first on the module with fake work, then a real ffmpeg killed over HTTP.
 */

import assert from 'node:assert/strict'
import fsp from 'node:fs/promises'
import path from 'node:path'
import { after, before, describe, test } from 'node:test'

import { getJob, post, setup, sleep, waitJob } from './helpers.js'

let t
let jobs

before(async () => {
  t = await setup('queue', { fixtures: ['sample.mp4'] })
  jobs = await import('../lib/jobs.js')
})

after(async () => {
  jobs._reset()
  await t.stop()
})

/** Fake work that can be released from outside. */
function gate() {
  let open
  const opened = new Promise((resolve) => { open = resolve })
  return { opened, open }
}

async function settle(job, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs
  while (!['done', 'error', 'cancelled'].includes(job.status)) {
    if (Date.now() > deadline) throw new Error(`job ${job.id} stuck in ${job.status}`)
    await sleep(5)
  }
  // The slot frees a tick after the status flips.
  await sleep(5)
  return job
}

describe('queue', () => {
  test('runs RENDER_CONCURRENCY jobs at a time, in order', async () => {
    jobs._reset()
    let active = 0
    let peak = 0
    const order = []
    const submitted = []
    for (let i = 0; i < 10; i += 1) {
      submitted.push(jobs.submit('fake', async () => {
        order.push(i)
        active += 1
        peak = Math.max(peak, active)
        await sleep(20)
        active -= 1
        return { i }
      }))
    }
    assert.deepEqual(jobs.stats(), { running: 2, queued: 8 })
    for (const job of submitted) await settle(job)
    assert.equal(peak, 2)
    assert.deepEqual(order, [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert.deepEqual(submitted.map((j) => j.result.i), [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    assert.deepEqual(jobs.stats(), { running: 0, queued: 0 })
  })

  test('a failing job frees its slot and reports the error', async () => {
    jobs._reset()
    const bad = jobs.submit('fake', async () => { throw new Error('boom') })
    const good = jobs.submit('fake', async () => 'fine')
    await settle(bad)
    await settle(good)
    assert.equal(bad.status, 'error')
    assert.deepEqual(bad.error, { code: 'internal', message: 'boom', stderr_tail: null })
    assert.equal(good.status, 'done')
    assert.equal(jobs.stats().running, 0)
  })

  test('a queued job is cancelled without ever starting', async () => {
    jobs._reset()
    const g1 = gate()
    const g2 = gate()
    let thirdRan = false
    const first = jobs.submit('fake', () => g1.opened)
    const second = jobs.submit('fake', () => g2.opened)
    const third = jobs.submit('fake', async () => { thirdRan = true })
    assert.equal(third.status, 'queued')
    jobs.cancel(third.id)
    assert.equal(third.status, 'cancelled')
    assert.equal(jobs.stats().queued, 0)
    g1.open()
    g2.open()
    await settle(first)
    await settle(second)
    assert.equal(thirdRan, false)
  })

  test('a running job sees the abort, and a finished job stays finished', async () => {
    jobs._reset()
    let sawAbort = false
    const job = jobs.submit('fake', (ctx) => new Promise((resolve, reject) => {
      ctx.signal.addEventListener('abort', () => {
        sawAbort = true
        reject(new Error('aborted'))
      })
    }))
    assert.equal(job.status, 'running')
    await sleep(5)
    jobs.cancel(job.id)
    assert.equal(job.status, 'cancelled')
    await settle(job)
    assert.equal(sawAbort, true)
    assert.equal(job.error, null)

    const done = jobs.submit('fake', async () => 'x')
    await settle(done)
    jobs.cancel(done.id)
    assert.equal(done.status, 'done')
    assert.equal(jobs.cancel('nope'), null)
  })

  test('a job cancelled before its work starts never runs it', async () => {
    jobs._reset()
    let ran = false
    const job = jobs.submit('fake', async () => { ran = true })
    jobs.cancel(job.id)
    await settle(job)
    assert.equal(job.status, 'cancelled')
    assert.equal(ran, false)
    assert.equal(jobs.stats().running, 0)
  })

  test('progress is clamped and never goes backwards', async () => {
    jobs._reset()
    const seen = []
    const g = gate()
    const job = jobs.submit('fake', async (ctx) => {
      for (const f of [0.2, 0.1, 0.5, Number.NaN, 7, -1]) {
        ctx.progress(f)
        seen.push(job.progress)
      }
      await g.opened
    })
    await sleep(5)
    assert.deepEqual(seen, [0.2, 0.2, 0.5, 0.5, 1, 1])
    g.open()
    await settle(job)
    assert.equal(job.progress, 1)
  })

  test('finished jobs are forgotten after RENDER_JOB_TTL_MS', async () => {
    jobs._reset()
    const job = jobs.submit('fake', async () => 'x')
    await settle(job)
    const before = process.env.RENDER_JOB_TTL_MS
    process.env.RENDER_JOB_TTL_MS = '20'
    try {
      jobs.expire()
      assert.ok(jobs.get(job.id), 'expired too early')
      await sleep(40)
      jobs.expire()
      assert.equal(jobs.get(job.id), null)
    } finally {
      if (before === undefined) delete process.env.RENDER_JOB_TTL_MS
      else process.env.RENDER_JOB_TTL_MS = before
    }
  })
})

describe('scratch', () => {
  test('is removed after success and after failure', async () => {
    let dir
    await jobs.withScratch('scratch-ok', async (d) => {
      dir = d
      await fsp.writeFile(path.join(d, 'x'), 'x')
    })
    await assert.rejects(fsp.stat(dir), /ENOENT/)
    await assert.rejects(jobs.withScratch('scratch-bad', async (d) => {
      dir = d
      throw new Error('fail')
    }), /fail/)
    await assert.rejects(fsp.stat(dir), /ENOENT/)
  })

  test('the sweeper removes leftovers but not live work', async () => {
    const orphan = t.abs('cache/render/crashed-job')
    await fsp.mkdir(orphan, { recursive: true })
    await fsp.writeFile(path.join(orphan, 'half.mp4'), 'x')
    const g = gate()
    let live
    const running = jobs.withScratch('live-job', async (d) => {
      live = d
      await g.opened
    })
    await sleep(10)
    const removed = await jobs.sweepScratch()
    assert.equal(removed, 1)
    await assert.rejects(fsp.stat(orphan), /ENOENT/)
    assert.ok((await fsp.stat(live)).isDirectory())
    g.open()
    await running
  })
})

/** Processes whose working directory is inside `dir` (Linux /proc). */
async function processesIn(dir) {
  const found = []
  for (const pid of await fsp.readdir('/proc').catch(() => [])) {
    if (!/^\d+$/.test(pid)) continue
    try {
      const cwd = await fsp.readlink(`/proc/${pid}/cwd`)
      if (cwd === dir || cwd.startsWith(`${dir}/`)) found.push(pid)
    } catch (_) {
      // gone, or not ours to look at
    }
  }
  return found
}

describe('cancel over HTTP', () => {
  test('kills ffmpeg, removes scratch, publishes nothing', async () => {
    jobs._reset()
    const submitted = await post(t.base, '/crop', { input: 'files/fx/sample.mp4', output: 'files/out/huge.mp4', width: 4096, height: 4096, mode: 'blur' })
    assert.equal(submitted.status, 202, JSON.stringify(submitted.json))
    const id = submitted.json.job_id
    await waitJob(t.base, id, { until: ['running', 'done', 'error'] })
    await sleep(300)
    const scratch = path.join(await fsp.realpath(t.abs('cache/render')), id)
    assert.ok((await processesIn(scratch)).length > 0, 'ffmpeg was not running in the job scratch directory')

    const res = await fetch(`${t.base}/jobs/${id}`, { method: 'DELETE' })
    assert.equal(res.status, 200)
    assert.equal((await res.json()).status, 'cancelled')

    const deadline = Date.now() + 10_000
    for (;;) {
      const gone = await fsp.stat(scratch).then(() => false, () => true)
      const health = await (await fetch(`${t.base}/health`)).json()
      if (gone && health.queue.running === 0) break
      if (Date.now() > deadline) throw new Error('scratch or slot not released after cancel')
      await sleep(50)
    }
    assert.deepEqual(await processesIn(scratch), [])
    await assert.rejects(fsp.stat(t.abs('files/out/huge.mp4')), /ENOENT/)
    const { json } = await getJob(t.base, id)
    assert.equal(json.status, 'cancelled')
    assert.equal(json.result, null)
  })

  test('DELETE on a finished job leaves it as it was', async () => {
    const submitted = await post(t.base, '/trim', { input: 'files/fx/sample.mp4', output: 'files/out/short.mp4', end: 1 })
    const job = await waitJob(t.base, submitted.json.job_id)
    assert.equal(job.status, 'done')
    const res = await fetch(`${t.base}/jobs/${job.id}`, { method: 'DELETE' })
    assert.equal(res.status, 200)
    assert.equal((await res.json()).status, 'done')
    assert.ok((await fsp.stat(t.abs('files/out/short.mp4'))).size > 0)
  })
})
