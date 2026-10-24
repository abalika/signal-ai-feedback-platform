import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

// Use the installed compiler and Node's runner; no additional test framework.
const source = (await readFile(new URL('../src/api.ts', import.meta.url), 'utf8'))
  .replace(/import\.meta\.env/g, '({ DEV: false })')
const output = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText
const { request, API_URL } = await import(`data:text/javascript;base64,${Buffer.from(output).toString('base64')}`)
globalThis.window = globalThis

test('production requests use same origin and decode success', async () => {
  assert.equal(API_URL, '')
  globalThis.fetch = async (url) => { assert.equal(url, '/api/health'); return new Response('{"status":"ok"}') }
  assert.deepEqual(await request('/api/health'), { status: 'ok' })
})
test('422 field errors remain readable', async () => {
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: [{ loc: ['body', 'name'], msg: 'too long' }] }), { status: 422 })
  await assert.rejects(request('/api/projects'), { status: 422, message: 'name：too long' })
})
test('non JSON gateway failure is safe and retains status', async () => {
  globalThis.fetch = async () => new Response('<html>private gateway dump</html>', { status: 502 })
  await assert.rejects(request('/api/projects'), { status: 502, message: '请求失败（502），请稍后重试' })
})
test('network failure has actionable wording', async () => {
  globalThis.fetch = async () => { throw new TypeError('Failed to fetch') }
  await assert.rejects(request('/api/projects'), { status: 0, message: '无法连接本地服务，请确认服务已启动后重新连接' })
})
test('cancellation clears the pending fetch', async () => {
  globalThis.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new Error('aborted')))
  })
  const controller = new AbortController()
  const pending = request('/api/projects', { signal: controller.signal })
  controller.abort()
  await assert.rejects(pending, { status: 0, message: '请求已取消或超时，请刷新核对结果后再重试' })
})
test('invalid JSON success is not accepted as data', async () => {
  globalThis.fetch = async () => new Response('broken')
  await assert.rejects(request('/api/projects'), { message: '服务返回了无效数据，请刷新后重试' })
})
test('empty 204 is supported', async () => {
  globalThis.fetch = async () => new Response(null, { status: 204 })
  assert.equal(await request('/api/projects'), undefined)
})
