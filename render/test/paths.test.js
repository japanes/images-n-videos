/**
 * The path guards are the whole security boundary of this service: a request
 * must not read the Google key, the database or a backup, and must not write
 * outside files/ and cache/. Tested on the functions themselves, with real
 * files and real symlinks.
 */

import assert from 'node:assert/strict'
import fsp from 'node:fs/promises'
import path from 'node:path'
import { after, before, describe, test } from 'node:test'

import { DATA_ROOT, prepareData } from './helpers.js'

let dir
let outside
let paths
let Workspace

const isStatus = (status, re) => (err) => {
  assert.equal(err.status, status, `expected ${status}, got ${err.status}: ${err.message}`)
  if (re) assert.match(err.message, re)
  return true
}

before(async () => {
  dir = await prepareData('paths')
  // A place next to the data directory, which no path may reach.
  outside = path.join(DATA_ROOT, 'test-paths-outside')
  await fsp.rm(outside, { recursive: true, force: true })
  await fsp.mkdir(outside, { recursive: true })
  await fsp.writeFile(path.join(outside, 'loot.mp4'), 'not yours')

  await fsp.mkdir(path.join(dir, 'files/2026/10'), { recursive: true })
  await fsp.writeFile(path.join(dir, 'files/2026/10/clip.mp4'), 'video')
  await fsp.writeFile(path.join(dir, 'files/2026/10/still.png'), 'png')
  await fsp.writeFile(path.join(dir, 'secrets/google-key.json'), '{"private_key":"x"}')
  await fsp.writeFile(path.join(dir, 'backups/app-1.db'), 'db')
  await fsp.writeFile(path.join(dir, 'app.db'), 'db')
  await fsp.writeFile(path.join(dir, 'app.db-wal'), 'wal')
  await fsp.mkdir(path.join(dir, 'cache/render/job-1'), { recursive: true })
  await fsp.writeFile(path.join(dir, 'cache/render/job-1/in-1.mp4'), 'scratch')

  // Symlinks that try to get out, or into a forbidden area, from an allowed one.
  await fsp.symlink(path.join(outside, 'loot.mp4'), path.join(dir, 'files/escape.mp4'))
  await fsp.symlink(path.join(dir, 'secrets/google-key.json'), path.join(dir, 'files/key.mp4'))
  await fsp.symlink(outside, path.join(dir, 'files/out-dir'))
  await fsp.symlink(path.join(dir, 'secrets'), path.join(dir, 'files/secret-dir'))
  // A legitimate link that stays inside.
  await fsp.symlink(path.join(dir, 'files/2026/10/clip.mp4'), path.join(dir, 'files/alias.mp4'))

  paths = await import('../lib/paths.js')
  ;({ Workspace } = await import('../lib/ops/common.js'))
})

after(async () => {
  await fsp.rm(outside, { recursive: true, force: true })
})

describe('cleanRel', () => {
  test('normalises a relative path', () => {
    assert.equal(paths.cleanRel('./files//2026/./x.mp4', 'input'), 'files/2026/x.mp4')
  })

  for (const [label, value, re] of [
    ['an empty string', '', /non-empty/],
    ['a number', 42, /non-empty/],
    ['an absolute path', '/etc/passwd', /not absolute/],
    ['a Windows drive path', 'C:/Users/x.mp4', /not absolute/],
    ['a parent segment', 'files/../secrets/google-key.json', /"\.\."/],
    ['a bare parent', '..', /"\.\."/],
    ['a backslash', 'files\\x.mp4', /forward slashes/],
    ['a NUL byte', 'files/x.mp4\0.png', /NUL/],
    ['only dots and slashes', './/.', /name a file/],
    ['a path that is too long', `files/${'a'.repeat(1100)}`, /too long/],
  ]) {
    test(`rejects ${label}`, () => {
      assert.throws(() => paths.cleanRel(value, 'input'), isStatus(400, re))
    })
  }
})

describe('resolveInput', () => {
  test('returns the real path of a file inside', async () => {
    const real = await paths.resolveInput('files/2026/10/clip.mp4', 'input')
    assert.equal(real, await fsp.realpath(path.join(dir, 'files/2026/10/clip.mp4')))
  })

  test('follows a link that stays inside', async () => {
    const real = await paths.resolveInput('files/alias.mp4', 'input')
    assert.equal(real, await fsp.realpath(path.join(dir, 'files/2026/10/clip.mp4')))
  })

  test('a missing file is a 404', async () => {
    await assert.rejects(paths.resolveInput('files/nope.mp4', 'input'), isStatus(404, /not found/))
    await assert.rejects(paths.resolveInput('files/2026/10/clip.mp4/x', 'input'), isStatus(404))
  })

  test('a directory is a 400', async () => {
    await assert.rejects(paths.resolveInput('files/2026', 'input'), isStatus(400, /not a regular file/))
  })

  for (const rel of ['secrets/google-key.json', 'backups/app-1.db', 'app.db', 'app.db-wal', 'cache/render/job-1/in-1.mp4']) {
    test(`refuses to read ${rel}`, async () => {
      await assert.rejects(paths.resolveInput(rel, 'input'), isStatus(400, /not readable/))
    })
  }

  test('refuses a link that points out of the data directory', async () => {
    await assert.rejects(paths.resolveInput('files/escape.mp4', 'input'), isStatus(400, /outside the data directory/))
    await assert.rejects(paths.resolveInput('files/out-dir/loot.mp4', 'input'), isStatus(400, /outside the data directory/))
  })

  test('refuses a link that points into a forbidden area', async () => {
    await assert.rejects(paths.resolveInput('files/key.mp4', 'input'), isStatus(400, /not readable/))
    await assert.rejects(paths.resolveInput('files/secret-dir/google-key.json', 'input'), isStatus(400, /not readable/))
  })

  test('checks the extension when asked', async () => {
    const real = await paths.resolveInput('files/2026/10/still.png', 'image', { exts: paths.IMAGE_EXT })
    assert.ok(real.endsWith('still.png'))
    await assert.rejects(paths.resolveInput('files/2026/10/clip.mp4', 'image', { exts: paths.IMAGE_EXT }), isStatus(400, /must be one of/))
  })
})

describe('resolveOutput', () => {
  test('creates the parent folders and reports the relative path', async () => {
    const out = await paths.resolveOutput('files/2026/11/new/cut.mp4', 'output', paths.VIDEO_EXT)
    assert.equal(out.rel, 'files/2026/11/new/cut.mp4')
    assert.equal(out.abs, path.join(await fsp.realpath(dir), 'files/2026/11/new/cut.mp4'))
    assert.ok((await fsp.stat(path.join(dir, 'files/2026/11/new'))).isDirectory())
  })

  test('allows cache/ but not render scratch', async () => {
    const out = await paths.resolveOutput('cache/thumbs/a.jpg', 'output', paths.JPEG_EXT)
    assert.equal(out.rel, 'cache/thumbs/a.jpg')
    await assert.rejects(paths.resolveOutput('cache/render/x.mp4', 'output', paths.VIDEO_EXT), isStatus(400, /inside files\/ or cache\//))
  })

  for (const rel of ['secrets/x.mp4', 'backups/x.mp4', 'x.mp4', 'fonts/x.mp4', 'app.db']) {
    test(`refuses to write ${rel}`, async () => {
      await assert.rejects(paths.resolveOutput(rel, 'output', null), isStatus(400, /inside files\/ or cache\//))
    })
  }

  test('checks the extension', async () => {
    await assert.rejects(paths.resolveOutput('files/x.mov', 'output', paths.VIDEO_EXT), isStatus(400, /must end with/))
  })

  test('refuses the publish temp name and an existing directory', async () => {
    await assert.rejects(paths.resolveOutput('files/.vf-tmp-x.mp4', 'output', paths.VIDEO_EXT), isStatus(400, /reserved/))
    await fsp.mkdir(path.join(dir, 'files/taken.mp4'), { recursive: true })
    await assert.rejects(paths.resolveOutput('files/taken.mp4', 'output', paths.VIDEO_EXT), isStatus(400, /existing directory/))
  })

  test('refuses a folder link that leads out, and creates nothing there', async () => {
    await assert.rejects(paths.resolveOutput('files/out-dir/new/x.mp4', 'output', paths.VIDEO_EXT), isStatus(400, /outside the data directory/))
    await assert.rejects(fsp.stat(path.join(outside, 'new')), /ENOENT/)
  })

  test('refuses a folder link into a forbidden area', async () => {
    await assert.rejects(paths.resolveOutput('files/secret-dir/x.mp4', 'output', paths.VIDEO_EXT), isStatus(400, /inside files\/ or cache\//))
  })
})

describe('resolveOutputDir', () => {
  test('creates the folder', async () => {
    const out = await paths.resolveOutputDir('cache/tmp/stt-1', 'output_dir')
    assert.equal(out.rel, 'cache/tmp/stt-1')
    assert.ok((await fsp.stat(out.abs)).isDirectory())
  })

  test('refuses a folder outside files/ and cache/', async () => {
    await assert.rejects(paths.resolveOutputDir('secrets/parts', 'output_dir'), isStatus(400))
    await assert.rejects(paths.resolveOutputDir('cache/render/x', 'output_dir'), isStatus(400))
    await assert.rejects(paths.resolveOutputDir('files/out-dir', 'output_dir'), isStatus(400, /outside/))
  })
})

describe('publish', () => {
  test('replaces the destination in one step', async () => {
    const src = path.join(dir, 'cache/render/job-1/out.mp4')
    const dest = path.join(dir, 'files/2026/10/clip.mp4')
    await fsp.writeFile(src, 'new video')
    await paths.publish(src, dest)
    assert.equal(await fsp.readFile(dest, 'utf8'), 'new video')
    await assert.rejects(fsp.stat(src), /ENOENT/)
  })
})

describe('brand fonts', () => {
  test('come from <data>/fonts, and only from inside the data directory', async () => {
    await fsp.mkdir(path.join(dir, 'fonts/brand'), { recursive: true })
    await fsp.writeFile(path.join(dir, 'fonts/brand/Brand-Bold.ttf'), 'font')
    await fsp.writeFile(path.join(dir, 'fonts/readme.txt'), 'not a font')
    await fsp.writeFile(path.join(outside, 'stolen.ttf'), 'font')
    await fsp.symlink(path.join(outside, 'stolen.ttf'), path.join(dir, 'fonts/stolen.ttf'))

    const scratch = path.join(dir, 'cache/render/fonts-test')
    await fsp.mkdir(scratch, { recursive: true })
    const ws = new Workspace({ dir: scratch })
    const name = await ws.fonts([])
    const links = await fsp.readdir(path.join(scratch, name))
    assert.equal(links.length, 1, `font links: ${links.join(', ')}`)
    const target = await fsp.realpath(path.join(scratch, name, links[0]))
    assert.ok(target.endsWith('fonts/brand/Brand-Bold.ttf'), target)
  })
})
