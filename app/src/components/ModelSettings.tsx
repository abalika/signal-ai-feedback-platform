import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { request } from '../api'
import { Icon, Modal } from './Shared'

type Settings = {
  base_url: string; model: string; has_key: boolean; key_mask: string
  remembered: boolean; source: string; mode: 'live' | 'offline'; csrf_token: string; load_error: boolean
}
type Proof = { verification_token: string; latency_ms: number }

export function ModelSettings({ onClose, onChanged }: { onClose: () => void; onChanged: () => Promise<void> }) {
  const [status, setStatus] = useState<Settings | null>(null)
  const [baseUrl, setBaseUrl] = useState('')
  const [model, setModel] = useState('')
  const [key, setKey] = useState('')
  const [visible, setVisible] = useState(false)
  const [remember, setRemember] = useState(false)
  const [proof, setProof] = useState<Proof | null>(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const form = useRef<HTMLFormElement>(null)

  function applyStatus(next: Settings) {
    setStatus(next); setBaseUrl(next.base_url); setModel(next.model); setRemember(next.remembered)
    setKey(''); setVisible(false); setProof(null)
  }
  useEffect(() => {
    const controller = new AbortController()
    request<Settings>('/api/model-settings', { signal: controller.signal }).then(applyStatus).catch((e) => {
      if (!controller.signal.aborted) setError(e instanceof Error ? e.message : '无法加载模型设置')
    })
    return () => controller.abort()
  }, [])

  function changed() { setProof(null); setMessage(''); setError('') }
  function payload() { return { base_url: baseUrl.trim(), model: model.trim(), api_key: key, remember } }
  const headers = { 'X-Signal-Settings-Token': status?.csrf_token ?? '' }

  async function test() {
    if (!form.current?.reportValidity() || busy || !status) return
    setBusy('test'); setError(''); setMessage(''); setProof(null)
    try {
      const result = await request<Proof>('/api/model-settings/test', { method: 'POST', headers, body: JSON.stringify(payload()) })
      setProof(result); setMessage(`连接成功 · ${result.latency_ms} ms。点击“保存并启用”即可开始使用。`)
    } catch (e) { setError(e instanceof Error ? e.message : '连接测试失败') }
    finally { setBusy('') }
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    if (!proof || busy || !status) return
    setBusy('save'); setError(''); setMessage('')
    try {
      const next = await request<Settings>('/api/model-settings', { method: 'PUT', headers, body: JSON.stringify({ ...payload(), verification_token: proof.verification_token }) })
      applyStatus(next)
      await onChanged()
      setMessage(next.remembered ? '已启用真实模型，并在本机记住配置。可以直接分析反馈。' : '已启用真实模型，本次运行期间有效。可以直接分析反馈。')
    } catch (e) { setError(e instanceof Error ? e.message : '保存失败') }
    finally { setBusy('') }
  }
  async function changeMode(clear = false) {
    if (busy || !status) return
    setBusy(clear ? 'clear' : 'offline'); setError(''); setMessage('')
    try {
      const next = await request<Settings>(clear ? '/api/model-settings' : '/api/model-settings/offline', { method: clear ? 'DELETE' : 'POST', headers })
      applyStatus(next); await onChanged()
      setMessage(clear ? '网页配置已删除，已切回离线演示。原有环境变量配置未被修改。' : '已切回离线演示，不调用模型。已保存的配置仍可再次启用。')
    } catch (e) { setError(e instanceof Error ? e.message : '操作未完成') }
    finally { setBusy('') }
  }

  return <Modal title="模型设置" description="填写你的模型服务，测试连接后即可启用，无需重启。" onClose={onClose}>
    {!status && !error && <div className="settings-state" role="status">正在读取本机配置…</div>}
    {error && <div className="error-banner" role="alert"><Icon name="alert" size={17} /><span>{error}</span></div>}
    {status && <>
      <div className="settings-state"><Icon name="shield" size={21} /><div><strong>{status.mode === 'live' ? '真实模型已启用' : '当前使用离线演示'}</strong><p>{status.has_key ? `API key ${status.key_mask} · ${status.remembered ? '本机已记住' : status.source === 'environment' ? '来自后端环境配置' : '仅本次运行'}` : '尚未配置 API key，离线演示仍可直接使用。'}</p></div></div>
      {status.load_error && <div className="error-banner" role="alert">保存的本机配置无法读取，请重新填写并测试连接。</div>}
      <form ref={form} className="modal-form model-settings-form" onSubmit={(event) => void save(event)}>
        <fieldset disabled={Boolean(busy)}>
          <label htmlFor="model-base-url">接口地址 <span>Base URL</span></label>
          <input id="model-base-url" type="url" autoComplete="off" placeholder="https://api.example.com/v1" value={baseUrl} required maxLength={500} onChange={(e) => { setBaseUrl(e.target.value); changed() }} aria-describedby="model-url-help" />
          <small id="model-url-help">填写供应商提供的兼容地址。本机网关可使用 HTTP，其他地址使用 HTTPS。</small>
          <label htmlFor="model-name">模型名称</label>
          <input id="model-name" autoComplete="off" placeholder="供应商提供的模型 ID" value={model} required maxLength={120} onChange={(e) => { setModel(e.target.value); changed() }} />
          <label htmlFor="model-api-key">API key {status.has_key && <span>留空沿用已有密钥</span>}</label>
          <div className="settings-secret"><input id="model-api-key" type={visible ? 'text' : 'password'} autoComplete="new-password" spellCheck={false} placeholder={status.has_key ? '••••••••（已配置，不会回显）' : '输入你的 API key'} value={key} required={!status.has_key} maxLength={4096} onChange={(e) => { setKey(e.target.value); changed() }} aria-describedby="model-key-help" /><button type="button" className="text-button" aria-pressed={visible} onClick={() => setVisible(!visible)}>{visible ? '隐藏' : '显示'}</button></div>
          <small id="model-key-help">密钥仅交给本机后端，不写入浏览器存储。更换接口地址时需重新输入。</small>
          <label className="settings-remember"><input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /><span>在本机记住，重启后继续使用<small>可选：写入后端本机配置文件；文件不加密，不会进入 Git 或交付包。</small></span></label>
        </fieldset>
        {message && <div className="settings-success" role="status"><Icon name="check" size={18} /><span>{message}</span></div>}
        <p className="settings-test-note">测试连接会发送 1 条极短请求；启用后，分析反馈将产生真实模型用量。</p>
        <div className="modal-actions"><button type="button" className="secondary-button" disabled={Boolean(busy)} onClick={() => void test()}>{busy === 'test' ? '正在测试…' : '测试连接'}</button><button type="submit" className="primary-button" disabled={!proof || Boolean(busy)}>{busy === 'save' ? '正在启用…' : '保存并启用'}</button></div>
      </form>
      <div className="settings-other-actions"><button className="text-button" type="button" disabled={Boolean(busy) || status.mode === 'offline'} onClick={() => void changeMode()}>使用离线演示</button><button className="text-button" type="button" disabled={Boolean(busy) || status.source !== 'web'} onClick={() => void changeMode(true)}>删除网页配置</button></div>
    </>}
  </Modal>
}
