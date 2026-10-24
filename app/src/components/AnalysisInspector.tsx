import { useState } from 'react'
import type { Analysis, Evidence, Feedback, Trace } from '../types'
import { Icon } from './Shared'
import { formatDate, statusMeta } from '../ui'

type Props = {
  feedback: Feedback
  analysis: Analysis | null
  traces: Trace[]
  reviewConfirmed: boolean
  setReviewConfirmed: (value: boolean) => void
  onAnalyze: () => void
  onApprove: (title: string, reviewerNote: string) => void
  loading: string | null
  demoMode?: boolean
  aiConfigured: boolean
}

export function AnalysisInspector(props: Props) {
  const { feedback, analysis, traces, reviewConfirmed, setReviewConfirmed, onAnalyze, onApprove, loading, aiConfigured } = props
  const [title, setTitle] = useState(analysis?.proposed_task ?? '')
  const [reviewerNote, setReviewerNote] = useState('')
  const unavailable = analysis?.model_mode === 'unavailable'

  return <section className="inspector panel">
    <div className="inspector-heading"><div><span className="panel-eyebrow">REVIEW INSPECTOR</span><h2>处理建议与证据</h2></div><span className="live-label"><span />LIVE TRACE</span></div>
    <div className="selected-feedback"><div className="selected-feedback-head"><div><span className="feedback-source">{feedback.source}</span><span className={`status-badge ${statusMeta(feedback.status).tone}`}>{statusMeta(feedback.status).label}</span></div><span className="feedback-id">FB-{String(feedback.id).padStart(4, '0')}</span></div><p>{feedback.content}</p></div>
    {!analysis ? <div className="analysis-start">
      <div className="analysis-orb"><Icon name="sparkle" size={25} /></div><strong>还没有分析结果</strong>
      <p>请求后端分析服务后，系统会展示分类、摘要、建议任务和资料依据。</p>
      <button type="button" className="primary-button" onClick={onAnalyze} disabled={loading === 'analyze'}><Icon name="sparkle" size={16} />{loading === 'analyze' ? '分析中…' : props.demoMode ? '播放固定演示' : '请求 AI 分析'}</button>
      {!aiConfigured && <div className="inline-warning"><Icon name="alert" size={15} />当前服务声明 AI 未配置，请求将返回明确的不可用状态。</div>}
    </div> : unavailable ? <div className="unavailable-state">
      <div className="unavailable-icon"><Icon name="alert" size={21} /></div><strong>暂时无法生成有依据的分析</strong>
      <p>{analysis.summary} 平台不会基于不可用结果创建工单。</p><div className="mode-row"><span>model_mode</span><code>{analysis.model_mode}</code></div>
    </div> : <div className="analysis-result">
      <div className="result-topline"><span className="ai-badge"><Icon name="sparkle" size={13} />{analysis.model_mode === 'demo' ? '离线固定回放' : 'AI 分析'}</span><span className="result-category">{analysis.category || '未分类'}</span></div>
      <div className="result-block"><span className="result-label">摘要</span><p>{analysis.summary || '后端未返回摘要。'}</p></div>
      <div className="result-block"><span className="result-label">建议回复</span><p>{analysis.suggested_reply || '后端未返回建议回复。'}</p></div>
      <div className="result-block task-block"><span className="result-label">AI 建议任务</span><p>{analysis.proposed_task || '后端未返回可执行任务。'}</p></div>
      <EvidenceList evidence={analysis.evidence} />
      <div className="review-action">
        <div className="review-editor">
          <label>最终工单标题<textarea value={title} maxLength={240} rows={3} onChange={(event) => { setTitle(event.target.value); setReviewConfirmed(false) }} /></label>
          <label>审核备注（可选）<textarea value={reviewerNote} maxLength={2000} rows={3} placeholder="记录修改原因、待核实事项或验收条件" onChange={(event) => { setReviewerNote(event.target.value); setReviewConfirmed(false) }} /></label>
        </div>
        <label className="review-check"><input type="checkbox" checked={reviewConfirmed} onChange={(event) => setReviewConfirmed(event.target.checked)} /><span className="fake-checkbox"><Icon name="check" size={12} /></span><span>我已核对用户原文、资料依据和最终工单内容</span></label>
        <button type="button" className="primary-button full" disabled={!reviewConfirmed || !title.trim() || loading === 'approve'} onClick={() => onApprove(title, reviewerNote)}>{loading === 'approve' ? '创建中…' : '确认并创建技术工单'}<Icon name="arrow" size={15} /></button>
        <small className="review-hint">系统会同时保存 AI 原建议、人工最终标题和审核备注。</small>
      </div>
    </div>}
    <TraceList traces={traces} />
  </section>
}

function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return <div className="evidence-block"><div className="evidence-heading"><span className="result-label">资料依据</span><span>{evidence.length} 条引用</span></div>{evidence.length === 0 ? <p className="no-evidence">后端未返回资料依据，请谨慎处理。</p> : <div className="evidence-list">{evidence.map((item) => <div className="evidence-item" key={`${item.document_id}-${item.title}`}><div className="evidence-doc"><Icon name="book" size={14} /><strong>{item.title}</strong><span>DOC-{String(item.document_id).padStart(3, '0')}</span></div><p>{item.excerpt}</p></div>)}</div>}</div>
}

function TraceList({ traces }: { traces: Trace[] }) {
  const modelCalls = traces.map(parseTrace).filter((item) => item.kind === 'model')
  const elapsed = modelCalls.reduce((sum, item) => sum + item.elapsedMs, 0)
  const tokens = modelCalls.reduce((sum, item) => sum + item.totalTokens, 0)
  return <div className="trace-block">
    <div className="trace-heading"><span className="result-label">执行记录</span><span>{traces.length ? `${traces.length} steps` : '等待记录'}</span></div>
    {modelCalls.length > 0 && <div className="trace-summary"><span>模型调用 {modelCalls.length} 次</span><span>{elapsed ? `累计 ${elapsed} ms` : '等待耗时数据'}</span><span>{tokens ? `${tokens} tokens` : '等待 token 数据'}</span></div>}
    {traces.length === 0 ? <p className="trace-empty">分析后会在这里留下请求、检索和结果状态。</p> : <div className="trace-list">{traces.map((trace) => {
      const item = parseTrace(trace)
      return <div className={`trace-item trace-${item.kind}`} key={trace.id}><span className="trace-marker" /><div><div className="trace-title"><strong>{item.title}</strong>{item.status && <span>{item.status}</span>}</div><p>{item.summary}</p><div className="trace-meta">{item.elapsedMs > 0 && <span>{item.elapsedMs} ms</span>}{item.totalTokens > 0 && <span>{item.totalTokens} tokens</span>}<span>{formatDate(trace.created_at)}</span></div><details><summary>查看原始记录</summary><code>{trace.detail}</code></details></div></div>
    })}</div>}
  </div>
}

type ParsedTrace = { kind: string; title: string; status: string; summary: string; elapsedMs: number; totalTokens: number }

function parseTrace(trace: Trace): ParsedTrace {
  let data: Record<string, unknown> = {}
  try { data = JSON.parse(trace.detail) as Record<string, unknown> } catch { /* older plain-text error trace */ }
  const number = (key: string) => typeof data[key] === 'number' ? data[key] as number : 0
  if (trace.step === 'model' || trace.step === 'replay') {
    const phase = data.phase === 'tool_plan' ? '工具规划' : data.phase === 'recommendation' ? '生成建议' : '模型调用'
    const usage = typeof data.usage === 'object' && data.usage ? data.usage as Record<string, unknown> : data
    const totalTokens = typeof usage.total_tokens === 'number' ? usage.total_tokens : number('total_tokens')
    return { kind: trace.step === 'replay' ? 'replay' : 'model', title: phase, status: String(data.status ?? ''), summary: trace.step === 'replay' ? '固定回放，未调用模型' : String(data.model ?? '模型信息未返回'), elapsedMs: number('elapsed_ms'), totalTokens }
  }
  if (trace.step === 'tool') return { kind: 'tool', title: '执行只读工具', status: data.fallback ? 'fallback' : 'ok', summary: String(data.tool ?? '未知工具'), elapsedMs: 0, totalTokens: 0 }
  if (trace.step === 'retrieval') return { kind: 'retrieval', title: '检索项目资料', status: 'ok', summary: `${String(data.algorithm ?? 'deterministic')} · 候选 ${String(data.document_count ?? 0)} 份，选中 ${Array.isArray(data.selected_document_ids) ? data.selected_document_ids.length : 0} 份`, elapsedMs: 0, totalTokens: 0 }
  if (trace.step === 'review') return { kind: 'review', title: '人工审核写入', status: String(data.status ?? ''), summary: `最终标题 ${String(data.title_length ?? 0)} 字，审核备注 ${String(data.reviewer_note_length ?? 0)} 字`, elapsedMs: 0, totalTokens: 0 }
  if (trace.step === 'ticket_status') return { kind: 'review', title: '工单状态迁移', status: String(data.to ?? ''), summary: `${String(data.from ?? '')} → ${String(data.to ?? '')}，解决说明 ${String(data.note_length ?? 0)} 字`, elapsedMs: 0, totalTokens: 0 }
  if (trace.step === 'error') return { kind: 'error', title: '安全降级', status: 'error', summary: trace.detail, elapsedMs: 0, totalTokens: 0 }
  return { kind: trace.step, title: trace.step, status: '', summary: trace.detail, elapsedMs: 0, totalTokens: 0 }
}
