#!/usr/bin/env node
/**
 * Render document pages to images for agent-side OCR.
 *
 * This script does not call a vision API. It prepares page images and a
 * manifest so the active TTG OS model can read the images directly.
 */

import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync, copyFileSync, mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, extname, isAbsolute, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const SCRIPT_DIR = dirname(fileURLToPath(import.meta.url))
const IMAGE_EXTENSIONS = new Set(['.png', '.jpg', '.jpeg', '.webp', '.bmp', '.tif', '.tiff'])
const OFFICE_EXTENSIONS = new Set([
  '.doc', '.docx', '.rtf', '.odt',
  '.ppt', '.pptx', '.odp',
  '.xls', '.xlsx', '.ods',
  '.html', '.htm', '.txt', '.csv',
])

function usage() {
  process.stdout.write(`Usage:
  node scripts/iris_pdf_to_images.mjs <input.pdf|image|office-file> --out-dir <dir> [options]

Options:
  --pages <spec>        PDF pages, 1-based. Examples: 1, 1-3, 1-3,7, 5- (default: 1-)
  --dpi <number>        PDF render DPI (default: 220)
  --out-dir <dir>       Output directory for page images and manifest.json
  --prefix <name>       Output image prefix (default: page)
  --poppler-bin <dir>   Directory containing pdfinfo/pdftoppm
  --soffice-bin <file>  LibreOffice soffice executable for non-PDF conversion
  --timeout-ms <ms>     Per-command timeout (default: 120000)
  --help                Show this help

Poppler lookup order:
  1. --poppler-bin
  2. IRIS_POPPLER_BIN or POPPLER_BIN
  3. scripts/bin/poppler/<platform>/bin
  4. scripts/bin/poppler/<platform>
  5. scripts/bin
  6. PATH

Non-PDF office documents are converted to PDF first with LibreOffice soffice,
then rendered through the same PDF -> page image path.
`)
}

function parseArgs(argv) {
  const args = {
    input: undefined,
    pages: '1-',
    dpi: 220,
    outDir: undefined,
    prefix: 'page',
    popplerBin: undefined,
    sofficeBin: undefined,
    timeoutMs: 120000,
  }
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index]
    if (arg === '--help' || arg === '-h') {
      usage()
      process.exit(0)
    }
    if (arg === '--pages') args.pages = takeValue(argv, ++index, arg)
    else if (arg === '--dpi') args.dpi = Number(takeValue(argv, ++index, arg))
    else if (arg === '--out-dir') args.outDir = takeValue(argv, ++index, arg)
    else if (arg === '--prefix') args.prefix = takeValue(argv, ++index, arg)
    else if (arg === '--poppler-bin') args.popplerBin = takeValue(argv, ++index, arg)
    else if (arg === '--soffice-bin') args.sofficeBin = takeValue(argv, ++index, arg)
    else if (arg === '--timeout-ms') args.timeoutMs = Number(takeValue(argv, ++index, arg))
    else if (arg.startsWith('--')) throw new Error(`Unknown option ${arg}`)
    else if (args.input === undefined) args.input = arg
    else throw new Error(`Unexpected argument ${arg}`)
  }
  if (args.input === undefined) throw new Error('Missing input file')
  if (args.outDir === undefined) throw new Error('Missing --out-dir')
  if (!Number.isInteger(args.dpi) || args.dpi < 72 || args.dpi > 600) {
    throw new Error('--dpi must be an integer from 72 to 600')
  }
  if (!Number.isInteger(args.timeoutMs) || args.timeoutMs < 1000) {
    throw new Error('--timeout-ms must be at least 1000')
  }
  return args
}

function takeValue(argv, index, option) {
  const value = argv[index]
  if (value === undefined || value.startsWith('--')) throw new Error(`${option} requires a value`)
  return value
}

function platformName() {
  if (process.platform === 'win32') return 'win'
  if (process.platform === 'darwin') return 'macos'
  return 'linux'
}

function exeName(name) {
  return process.platform === 'win32' ? `${name}.exe` : name
}

function candidateDirs(popplerBin) {
  return [
    popplerBin,
    process.env.IRIS_POPPLER_BIN,
    process.env.POPPLER_BIN,
    join(SCRIPT_DIR, 'bin', 'poppler', platformName(), 'bin'),
    join(SCRIPT_DIR, 'bin', 'poppler', platformName()),
    join(SCRIPT_DIR, 'bin'),
  ].filter(Boolean).map(path => resolve(path))
}

function resolveBinary(name, popplerBin) {
  const executable = exeName(name)
  for (const dir of candidateDirs(popplerBin)) {
    const path = join(dir, executable)
    if (existsSync(path)) return path
  }
  return executable
}

function resolveSoffice(sofficeBin) {
  if (sofficeBin !== undefined) return resolve(sofficeBin)
  if (process.env.IRIS_SOFFICE_BIN) return resolve(process.env.IRIS_SOFFICE_BIN)
  if (process.env.SOFFICE_BIN) return resolve(process.env.SOFFICE_BIN)
  return process.platform === 'win32' ? 'soffice.exe' : 'soffice'
}

function commandEnv(binaryPath) {
  const env = { ...process.env }
  env.SAL_USE_VCLPLUGIN = env.SAL_USE_VCLPLUGIN ?? 'svp'
  if (isAbsolute(binaryPath)) {
    env.PATH = `${dirname(binaryPath)}${process.platform === 'win32' ? ';' : ':'}${env.PATH ?? ''}`
  }
  return env
}

function run(binary, args, timeoutMs) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(binary, args, {
      windowsHide: true,
      env: commandEnv(binary),
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    const timer = setTimeout(() => {
      child.kill('SIGTERM')
      reject(new Error(`${basename(binary)} timeout after ${timeoutMs}ms`))
    }, timeoutMs)
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', chunk => { stdout += chunk })
    child.stderr.on('data', chunk => { stderr += chunk })
    child.on('error', error => {
      clearTimeout(timer)
      reject(error)
    })
    child.on('close', code => {
      clearTimeout(timer)
      if (code === 0) resolvePromise({ stdout, stderr })
      else reject(new Error(`${basename(binary)} exited ${code}: ${(stderr || stdout).trim()}`))
    })
  })
}

function parsePageCount(pdfinfoOutput) {
  const match = /^Pages:\s+(\d+)\s*$/mi.exec(pdfinfoOutput)
  if (match === null) throw new Error('pdfinfo did not return a page count')
  return Number(match[1])
}

function parsePages(spec, pageCount) {
  const pages = new Set()
  for (const raw of spec.split(',')) {
    const part = raw.trim()
    if (part === '') continue
    if (part.includes('-')) {
      const [left, right] = part.split('-', 2)
      const start = left === '' ? 1 : Number(left)
      const end = right === '' ? pageCount : Number(right)
      if (!Number.isInteger(start) || !Number.isInteger(end) || start > end) {
        throw new Error(`Invalid page range ${part}`)
      }
      for (let page = start; page <= end; page += 1) pages.add(page)
    }
    else {
      const page = Number(part)
      if (!Number.isInteger(page)) throw new Error(`Invalid page ${part}`)
      pages.add(page)
    }
  }
  const ordered = [...pages].sort((a, b) => a - b)
  const invalid = ordered.filter(page => page < 1 || page > pageCount)
  if (invalid.length > 0) throw new Error(`Pages out of range 1-${pageCount}: ${invalid.join(', ')}`)
  return ordered
}

function imageMime(path) {
  const ext = extname(path).toLowerCase()
  if (ext === '.jpg' || ext === '.jpeg') return 'image/jpeg'
  if (ext === '.webp') return 'image/webp'
  if (ext === '.bmp') return 'image/bmp'
  if (ext === '.tif' || ext === '.tiff') return 'image/tiff'
  return 'image/png'
}

async function renderPdf(input, outDir, args) {
  const pdfinfo = resolveBinary('pdfinfo', args.popplerBin)
  const pdftoppm = resolveBinary('pdftoppm', args.popplerBin)
  const info = await run(pdfinfo, [input], args.timeoutMs)
  const pageCount = parsePageCount(info.stdout)
  const selectedPages = parsePages(args.pages, pageCount)
  const pages = []
  for (const page of selectedPages) {
    const prefix = join(outDir, `${args.prefix}-${String(page).padStart(4, '0')}`)
    await run(pdftoppm, [
      '-png',
      '-singlefile',
      '-r',
      String(args.dpi),
      '-f',
      String(page),
      '-l',
      String(page),
      input,
      prefix,
    ], args.timeoutMs)
    const imagePath = `${prefix}.png`
    if (!existsSync(imagePath)) throw new Error(`pdftoppm did not create ${imagePath}`)
    pages.push({ page, imagePath, mimeType: 'image/png' })
  }
  return {
    sourceType: 'pdf',
    pageCount,
    renderedPages: pages.length,
    pages,
    poppler: {
      pdfinfo,
      pdftoppm,
    },
  }
}

async function convertToPdf(input, outDir, args) {
  const soffice = resolveSoffice(args.sofficeBin)
  const convertDir = join(outDir, 'converted-pdf')
  mkdirSync(convertDir, { recursive: true })
  const profileDir = mkdtempSync(join(tmpdir(), 'iris-lo-profile-'))
  await run(soffice, [
    `-env:UserInstallation=${pathToFileUri(profileDir)}`,
    '--headless',
    '--nologo',
    '--nofirststartwizard',
    '--convert-to',
    'pdf',
    '--outdir',
    convertDir,
    input,
  ], args.timeoutMs)

  const expected = join(convertDir, `${basename(input, extname(input))}.pdf`)
  if (existsSync(expected)) return expected
  throw new Error(`LibreOffice conversion did not create ${expected}`)
}

function pathToFileUri(path) {
  let normalized = resolve(path).replaceAll('\\', '/')
  if (process.platform === 'win32' && !normalized.startsWith('/')) normalized = `/${normalized}`
  return `file://${encodeURI(normalized)}`
}

function prepareImage(input, outDir, args) {
  const ext = extname(input).toLowerCase() || '.png'
  const imagePath = join(outDir, `${args.prefix}-0001${ext}`)
  if (resolve(input) !== resolve(imagePath)) copyFileSync(input, imagePath)
  return {
    sourceType: 'image',
    pageCount: 1,
    renderedPages: 1,
    pages: [{ page: 1, imagePath, mimeType: imageMime(imagePath) }],
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2))
  const input = resolve(args.input)
  if (!existsSync(input)) throw new Error(`Input file not found: ${input}`)
  const outDir = resolve(args.outDir)
  mkdirSync(outDir, { recursive: true })

  const ext = extname(input).toLowerCase()
  let convertedPdfPath
  const renderResult = ext === '.pdf'
    ? await renderPdf(input, outDir, args)
    : IMAGE_EXTENSIONS.has(ext)
      ? prepareImage(input, outDir, args)
      : OFFICE_EXTENSIONS.has(ext)
        ? await (async () => {
          convertedPdfPath = await convertToPdf(input, outDir, args)
          const result = await renderPdf(convertedPdfPath, outDir, args)
          return { ...result, sourceType: 'converted-document', convertedPdfPath }
        })()
        : undefined
  if (renderResult === undefined) throw new Error('Unsupported file type. Use PDF or image files.')

  const manifest = {
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    sourcePath: input,
    outputDir: outDir,
    dpi: ext === '.pdf' ? args.dpi : undefined,
    ...renderResult,
    instructions: [
      'Call iris_vision_ocr with this manifest path to OCR each imagePath in page order.',
      'Use the returned markdownPath and jsonPath as the final OCR artifacts.',
      'Report exact output paths to the user.',
      'Do not summarize unless the user asks for a summary.',
    ],
  }
  const manifestPath = join(outDir, 'manifest.json')
  writeFileSync(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`, 'utf8')
  process.stdout.write(`${JSON.stringify({ ok: true, manifestPath, ...manifest }, null, 2)}\n`)
}

main().catch(error => {
  process.stderr.write(`Error: ${error instanceof Error ? error.message : String(error)}\n`)
  process.exit(1)
})
