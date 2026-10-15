/**
 * Every path the API accepts is relative to the data volume.
 *
 * render shares `/data` with the app and never sees a URL. That makes this file
 * the whole security boundary of the service: a request must not be able to
 * read the Google key, the database or a backup, and must not be able to write
 * anywhere except the media and cache folders.
 *
 * The checks, in order:
 *   1. shape — a non-empty string, no NUL, not absolute, no `..`, no backslash;
 *   2. area — inputs may not come from secrets/, backups/ or app.db*, outputs
 *      may only go to files/ or cache/ (and never into render's own scratch);
 *   3. reality — the real path, symlinks resolved, must still be inside the
 *      real data directory, and must still be in an allowed area.
 */

import { randomBytes } from 'node:crypto'
import fsp from 'node:fs/promises'
import path from 'node:path'

import { dataDir } from './config.js'
import { BadRequest, NotFound } from './errors.js'

/** Inputs are never read from here, whatever the request says. */
const DENIED_INPUT = [/^secrets(\/|$)/, /^backups(\/|$)/, /^app\.db/, /^cache\/render(\/|$)/]

/** Outputs may only land here. */
const ALLOWED_OUTPUT = [/^files\//, /^cache\//]
const DENIED_OUTPUT = [/^cache\/render(\/|$)/]

export const VIDEO_EXT = ['.mp4']
export const JPEG_EXT = ['.jpg', '.jpeg']
export const WEBP_EXT = ['.webp']
export const FONT_EXT = ['.ttf', '.otf', '.ttc', '.woff', '.woff2']
export const IMAGE_EXT = ['.png', '.jpg', '.jpeg', '.webp']
export const ASS_EXT = ['.ass', '.ssa']

/**
 * Shape check. Returns the path normalised to forward slashes, without `./`
 * segments or a trailing slash.
 */
export function cleanRel(value, field) {
  if (typeof value !== 'string' || !value.trim()) throw new BadRequest(`${field} must be a non-empty relative path`)
  if (value.length > 1024) throw new BadRequest(`${field} is too long`)
  if (value.includes('\0')) throw new BadRequest(`${field} must not contain NUL`)
  if (value.includes('\\')) throw new BadRequest(`${field} must use forward slashes`)
  if (value.startsWith('/') || /^[A-Za-z]:/.test(value)) {
    throw new BadRequest(`${field} must be relative to the data directory, not absolute`)
  }
  const parts = value.split('/').filter((p) => p !== '' && p !== '.')
  if (parts.some((p) => p === '..')) throw new BadRequest(`${field} must not contain ".."`)
  if (!parts.length) throw new BadRequest(`${field} must name a file`)
  return parts.join('/')
}

async function realData() {
  try {
    return await fsp.realpath(dataDir())
  } catch (err) {
    throw new Error(`data directory ${dataDir()} does not exist`, { cause: err })
  }
}

/** `child` relative to `root`, or null when it is not inside. */
function inside(root, child) {
  if (child === root) return ''
  const rel = path.relative(root, child)
  if (!rel || rel.startsWith('..') || path.isAbsolute(rel)) return null
  return rel.split(path.sep).join('/')
}

/**
 * An existing file to read. Returns its real absolute path.
 * Missing → 404 not_found; a directory or a forbidden area → 400.
 */
export async function resolveInput(value, field, { exts = null } = {}) {
  const rel = cleanRel(value, field)
  if (DENIED_INPUT.some((re) => re.test(rel))) throw new BadRequest(`${field}: this area of the data directory is not readable`)
  if (exts && !exts.includes(path.extname(rel).toLowerCase())) {
    throw new BadRequest(`${field} must be one of: ${exts.join(', ')}`)
  }
  const root = await realData()
  let real
  try {
    real = await fsp.realpath(path.join(root, rel))
  } catch (err) {
    if (err.code === 'ENOENT' || err.code === 'ENOTDIR') throw new NotFound(`${field}: file not found: ${rel}`)
    throw new BadRequest(`${field}: cannot open ${rel} (${err.code || err.message})`)
  }
  const realRel = inside(root, real)
  if (realRel === null || realRel === '') throw new BadRequest(`${field} points outside the data directory`)
  if (DENIED_INPUT.some((re) => re.test(realRel))) throw new BadRequest(`${field}: this area of the data directory is not readable`)
  const stat = await fsp.stat(real)
  if (!stat.isFile()) throw new BadRequest(`${field} is not a regular file: ${rel}`)
  return real
}

/** Optional input: undefined/null passes through as null. */
export async function resolveOptionalInput(value, field, opts) {
  if (value === undefined || value === null) return null
  return resolveInput(value, field, opts)
}

function checkOutputArea(rel, field) {
  if (!ALLOWED_OUTPUT.some((re) => re.test(rel)) || DENIED_OUTPUT.some((re) => re.test(rel))) {
    throw new BadRequest(`${field} must be inside files/ or cache/ (not cache/render/)`)
  }
}

/**
 * Create `relDir` (and parents) under the data dir and return its real path.
 *
 * Each existing ancestor is resolved before anything is created, so a symlink
 * planted somewhere along the way cannot make mkdir build directories outside
 * the volume.
 */
async function ensureDir(root, relDir, field) {
  const parts = relDir ? relDir.split('/') : []
  let current = root
  for (const part of parts) {
    const next = path.join(current, part)
    let real
    try {
      real = await fsp.realpath(next)
    } catch (err) {
      if (err.code !== 'ENOENT') throw new BadRequest(`${field}: cannot use ${relDir} (${err.code || err.message})`)
      try {
        await fsp.mkdir(next)
      } catch (mkErr) {
        if (mkErr.code !== 'EEXIST') throw mkErr
      }
      try {
        real = await fsp.realpath(next)
      } catch (_) {
        throw new BadRequest(`${field}: cannot create ${relDir}`)
      }
    }
    const realRel = inside(root, real)
    if (realRel === null) throw new BadRequest(`${field} points outside the data directory`)
    const stat = await fsp.stat(real)
    if (!stat.isDirectory()) throw new BadRequest(`${field}: ${part} is not a directory`)
    current = real
  }
  return current
}

/**
 * A file to write. Parent directories are created. Returns
 * `{ abs, rel }`: the absolute target (real parent + base name) and the
 * normalised relative path to report back.
 */
export async function resolveOutput(value, field, exts) {
  const rel = cleanRel(value, field)
  checkOutputArea(rel, field)
  const ext = path.extname(rel).toLowerCase()
  if (exts && !exts.includes(ext)) throw new BadRequest(`${field} must end with ${exts.join(' or ')}`)
  const base = path.posix.basename(rel)
  if (base.startsWith('.vf-tmp-')) throw new BadRequest(`${field}: reserved file name`)

  const root = await realData()
  const parent = await ensureDir(root, path.posix.dirname(rel) === '.' ? '' : path.posix.dirname(rel), field)
  const parentRel = inside(root, parent)
  const realRel = parentRel ? `${parentRel}/${base}` : base
  checkOutputArea(realRel, field)

  const abs = path.join(parent, base)
  try {
    const stat = await fsp.lstat(abs)
    if (stat.isDirectory()) throw new BadRequest(`${field} is an existing directory`)
  } catch (err) {
    if (err instanceof BadRequest) throw err
    if (err.code !== 'ENOENT') throw err
  }
  return { abs, rel }
}

/** A directory to write several files into (split-audio). Created if missing. */
export async function resolveOutputDir(value, field) {
  const rel = cleanRel(value, field)
  checkOutputArea(`${rel}/`, field)
  const root = await realData()
  const abs = await ensureDir(root, rel, field)
  const realRel = inside(root, abs)
  checkOutputArea(`${realRel}/`, field)
  return { abs, rel }
}

/**
 * Move a finished file from scratch to its destination.
 *
 * Scratch lives on the same volume (`cache/render/`), so this is a single
 * rename: the destination is either the old file or the complete new one, never
 * half of one. If the destination sits on another filesystem the file is first
 * copied next to it under a temporary name and then renamed, which keeps the
 * same guarantee.
 */
export async function publish(src, dest) {
  try {
    await fsp.rename(src, dest)
    return
  } catch (err) {
    if (err.code !== 'EXDEV') throw err
  }
  const tmp = path.join(path.dirname(dest), `.vf-tmp-${randomBytes(6).toString('hex')}-${path.basename(dest)}`)
  try {
    await fsp.copyFile(src, tmp)
    await fsp.rename(tmp, dest)
  } catch (err) {
    await fsp.rm(tmp, { force: true }).catch(() => {})
    throw err
  }
  await fsp.rm(src, { force: true }).catch(() => {})
}
