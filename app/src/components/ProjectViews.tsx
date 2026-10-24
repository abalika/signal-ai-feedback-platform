import { useState } from 'react'
import type { Document, Feedback, Metrics, Ticket } from '../types'
import { EmptyState, Icon, MetricCard, PanelHeader } from './Shared'
import { formatDate, shortText, statusMeta } from '../ui'

export function Overview({ documents, feedback, tickets, metrics, selectedFeedbackId, onSelectFeedback, onAddFeedback, onAddDocument, onOpenFeedback, onOpenEvaluations }: { documents: Document[]; feedback: Feedback[]; tickets: Ticket[]; metrics: Metrics | null; selectedFeedbackId: number | null; onSelectFeedback: (id: number) => void; onAddFeedback: () => void; onAddDocument: () => void; onOpenFeedback: () => void; onOpenEvaluations: () => void }) {
  const reviewed = feedback.filter((item) => ['ticket_created', 'ticketed', 'resolved'].includes(item.status)).length
  const analyzed = feedback.filter((item) => ['analyzed', 'in_review'].includes(item.status)).length
  const awaiting = feedback.length - reviewed - analyzed
  const pending = awaiting + analyzed
  const stages = [{ label: '等待分析', count: awaiting, tone: 'amber', icon: 'inbox' }, { label: '等待人工复核', count: analyzed, tone: 'blue', icon: 'shield' }, { label: '已建单 / 已解决', count: reviewed, tone: 'green', icon: 'check' }]
  const recent = [...feedback].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 4)
  return <div className="overview">
    <div className="workspace-note"><span className="note-icon"><Icon name="sparkle" size={17} /></span><p>{pending ? <>有 <strong>{pending} 条反馈</strong>等待你的下一步处理。让 AI 帮你梳理，把判断留给自己。</> : <>工作空间已就绪。从一条反馈开始，连接用户的声音与产品的下一步。</>}</p><span className="note-date">{new Intl.DateTimeFormat('zh-CN', { month: 'long', day: 'numeric', weekday: 'long', timeZone: 'Asia/Shanghai' }).format(new Date())}</span></div>
    <section className="metric-grid" aria-label="项目关键指标">
      <MetricCard label="累计用户反馈" value={feedback.length} suffix="条" icon="inbox" tone="green" detail={feedback.length ? `${awaiting} 条待分析 · ${analyzed} 条待复核` : '等待第一条用户的声音'} />
      <MetricCard label="待处理反馈" value={pending} suffix="条" icon="clock" tone="amber" detail={pending ? '分析与复核，让问题继续向前' : '当前没有待处理反馈'} />
      <MetricCard label="技术工单" value={tickets.length} suffix="张" icon="ticket" tone="blue" detail={`${tickets.filter((item) => item.status === 'done').length} 张已完成 · 每次流转均有记录`} />
      <MetricCard label="知识资料" value={documents.length} suffix="份" icon="book" tone="violet" detail={documents.length ? '为 AI 分析提供可追溯的依据' : '添加产品说明，建立回答依据'} />
    </section>
    <div className="overview-grid">
      <section className="panel queue-panel"><PanelHeader eyebrow="LATEST SIGNALS" title="最近的用户声音" description="每一条原话，都是理解产品的起点。" action={<button type="button" className="text-button" onClick={onOpenFeedback}>查看全部<Icon name="arrow" size={15} /></button>} />
        {recent.length === 0 ? <EmptyState icon="inbox" title="下一次改进，从倾听开始" description="录入一条用户反馈，让线索、分析和处理进展在这里相遇。" action={<button type="button" className="secondary-button small" onClick={onAddFeedback}><Icon name="plus" size={15} />录入第一条反馈</button>} /> : <div className="feedback-list">{recent.map((item) => <FeedbackRow key={item.id} item={item} selected={item.id === selectedFeedbackId} onClick={() => onSelectFeedback(item.id)} />)}</div>}
        <div className="panel-footnote"><Icon name="shield" size={14} />AI 提供处理建议，创建工单前由你确认。</div>
      </section>
      <section className="panel flow-panel"><PanelHeader eyebrow="WORKFLOW" title="反馈处理进展" description="从接收问题，到确认下一步。" />
        <div className="flow-summary"><div className="progress-ring" style={{ background: `conic-gradient(var(--accent) ${feedback.length ? reviewed / feedback.length * 360 : 0}deg, var(--surface-muted) 0)` }}><div><strong>{feedback.length ? Math.round(reviewed / feedback.length * 100) : 0}<small>%</small></strong><span>已进入交付</span></div></div><div className="flow-summary-copy"><strong>{reviewed}<span> / {feedback.length} 条</span></strong><p>已建单或已解决的反馈</p><span className="status-badge green">人工审核后流转</span></div></div>
        <div className="stage-list">{stages.map((stage) => <div key={stage.label}><span className={`stage-icon ${stage.tone}`}><Icon name={stage.icon} size={15} /></span><span>{stage.label}</span><strong>{stage.count}<small>条</small></strong></div>)}</div>
      </section>
    </div>
    <div className="overview-bottom">
      <section className="evaluation-spotlight"><div className="spotlight-heading"><span className="spotlight-icon"><Icon name="flask" size={23} /></span><span className="status-badge green">质量观察站</span></div><span className="panel-eyebrow">BUILT FOR BETTER ANSWERS</span><h2>好的回答，也需要被检验。</h2><p>固定题集、检索对比与失败复盘，<br />让每一次模型迭代都有据可循。</p><div className="spotlight-footer"><div><strong>36<span>条固定题</span></strong><span className="spotlight-divider" /><strong>30<span>条检索题</span></strong></div><button type="button" className="primary-button" onClick={onOpenEvaluations}>进入评测中心<Icon name="arrow" size={16} /></button></div><small>历史基线与最新复测分开记录 · 查看逐题证据</small></section>
      <section className="panel observability-panel"><PanelHeader eyebrow="UNDER THE HOOD" title="运行观察" description="来自当前项目的真实调用记录。" /><dl className="observability-list"><div><dt><Icon name="pulse" size={16} />模型调用</dt><dd>{metrics?.model_calls ?? '—'}<span>次</span></dd></div><div><dt><Icon name="clock" size={16} />P95 调用耗时</dt><dd>{metrics?.model_latency_p95_ms != null ? (metrics.model_latency_p95_ms / 1000).toFixed(2) : '—'}<span>秒</span></dd></div><div><dt><Icon name="layers" size={16} />累计 Token</dt><dd>{metrics ? metrics.total_tokens.toLocaleString('zh-CN') : '—'}</dd></div></dl><button type="button" className="knowledge-shortcut" onClick={onAddDocument}><span className="context-icon"><Icon name="book" size={18} /></span><span><strong>知识越清晰，回答越可靠</strong><small>为项目补充一份产品资料</small></span><Icon name="arrow" size={17} /></button></section>
    </div>
  </div>
}

function FeedbackRow({ item, selected, onClick }: { item: Feedback; selected: boolean; onClick: () => void }) {
  const meta = statusMeta(item.status)
  return <button type="button" className={`feedback-row ${selected ? 'selected' : ''}`} onClick={onClick}><div className="feedback-row-main"><span className="feedback-source">{item.source}</span><span className={`status-badge ${meta.tone}`}>{meta.label}</span><strong>{shortText(item.content, 96)}</strong><small><Icon name="clock" size={12} />{formatDate(item.created_at)}</small></div><Icon name="arrow" size={16} /></button>
}

export function DocumentsView({ documents, onAdd }: { documents: Document[]; onAdd: () => void }) {
  return <section className="panel full-panel"><PanelHeader eyebrow="KNOWLEDGE BASE" title="产品资料" description="当前项目的可检索资料。保持内容短而准确，便于回溯 AI 的引用。" action={<button type="button" className="primary-button small" onClick={onAdd}><Icon name="plus" size={14} />添加资料</button>} />{documents.length === 0 ? <EmptyState icon="book" title="资料库为空" description="先添加产品说明、常见问题或版本记录。" action={<button type="button" className="secondary-button small" onClick={onAdd}><Icon name="plus" size={14} />添加第一份资料</button>} /> : <div className="document-grid">{documents.map((document) => <article className="document-card" key={document.id}><div className="document-card-top"><div className="document-icon"><Icon name="book" size={17} /></div><span className="doc-date">{formatDate(document.created_at)}</span></div><h3>{document.title}</h3><p>{shortText(document.content, 180)}</p><div className="document-footer"><span>DOC-{String(document.id).padStart(3, '0')}</span><span>{document.content.length} 字</span></div></article>)}</div>}</section>
}

export function FeedbackView({ feedback, selectedFeedbackId, onSelect, onAdd, filtered = false }: { feedback: Feedback[]; selectedFeedbackId: number | null; onSelect: (id: number) => void; onAdd: () => void; filtered?: boolean }) {
  return <section className="panel full-panel"><PanelHeader eyebrow="USER SIGNALS" title="反馈收件箱" description="每条反馈都保留来源、原文和处理状态；AI 只提供建议，不会直接对外回复。" action={<button type="button" className="primary-button small" onClick={onAdd}><Icon name="plus" size={14} />录入反馈</button>} />{feedback.length === 0 ? <EmptyState icon="inbox" title={filtered ? '没有找到匹配的反馈' : '收件箱为空'} description={filtered ? '试试其他关键词，或清除搜索查看全部反馈。' : '添加一条真实试用反馈，看看它如何走完分析与复核流程。'} action={<button type="button" className="secondary-button small" onClick={onAdd}><Icon name="plus" size={14} />录入第一条反馈</button>} /> : <div className="feedback-table"><div className="table-head"><span>来源 / 原文</span><span>状态</span><span>时间</span><span /></div>{feedback.map((item) => { const meta = statusMeta(item.status); return <button type="button" className={`table-row ${item.id === selectedFeedbackId ? 'selected' : ''}`} key={item.id} onClick={() => onSelect(item.id)}><span><strong>{item.source}</strong><small>{shortText(item.content, 96)}</small></span><span><span className={`status-badge ${meta.tone}`}>{meta.label}</span></span><span className="table-date">{formatDate(item.created_at)}</span><Icon name="arrow" size={15} /></button> })}</div>}</section>
}

export function TicketsView({ tickets, feedback, onUpdate, loading }: { tickets: Ticket[]; feedback: Feedback[]; onUpdate: (id: number, status: string, note: string) => void; loading: string | null }) {
  const sourceFor = (feedbackId: number) => feedback.find((item) => item.id === feedbackId)?.source ?? `反馈 #${feedbackId}`
  const [filter, setFilter] = useState('all')
  const [notes, setNotes] = useState<Record<number, string>>({})
  const counts = { open: tickets.filter((ticket) => ticket.status === 'open').length, in_progress: tickets.filter((ticket) => ticket.status === 'in_progress').length, done: tickets.filter((ticket) => ticket.status === 'done').length }
  const visible = filter === 'all' ? tickets : tickets.filter((ticket) => ticket.status === filter)
  const statusLabel = (status: string) => status === 'in_progress' ? '处理中' : status === 'done' ? '已完成' : '待处理'
  return <section className="panel full-panel ticket-lifecycle">
    <PanelHeader eyebrow="DELIVERY QUEUE" title="技术工单" description="从人工审核到处理完成，每次状态变化都有审计记录。" />
    <div className="ticket-filters"><button className={filter === 'all' ? 'active' : ''} onClick={() => setFilter('all')}>全部 {tickets.length}</button><button className={filter === 'open' ? 'active' : ''} onClick={() => setFilter('open')}>待处理 {counts.open}</button><button className={filter === 'in_progress' ? 'active' : ''} onClick={() => setFilter('in_progress')}>处理中 {counts.in_progress}</button><button className={filter === 'done' ? 'active' : ''} onClick={() => setFilter('done')}>已完成 {counts.done}</button></div>
    {tickets.length === 0 ? <EmptyState icon="ticket" title="还没有技术工单" description="分析一条反馈并确认建议任务后，工单会出现在这里。" /> : visible.length === 0 ? <EmptyState icon="ticket" title="当前筛选没有工单" description="切换其他状态查看工单。" /> : <div className="ticket-cards">{visible.map((ticket) => <article className={`ticket-card ticket-${ticket.status}`} key={ticket.id}>
      <div className="ticket-card-head"><div><span>TICKET-{String(ticket.id).padStart(4, '0')}</span><h3>{ticket.title}</h3></div><span className={`status-badge ${ticket.status === 'done' ? 'green' : ticket.status === 'in_progress' ? 'blue' : 'amber'}`}>{statusLabel(ticket.status)}</span></div>
      <div className="ticket-card-meta"><span>来源：{sourceFor(ticket.feedback_id)}</span><span>创建：{formatDate(ticket.created_at)}</span>{ticket.updated_at && <span>更新：{formatDate(ticket.updated_at)}</span>}</div>
      {ticket.reviewer_note && <p className="ticket-note"><strong>审核备注</strong>{ticket.reviewer_note}</p>}
      {ticket.status === 'done' && <p className="ticket-resolution"><strong>解决说明</strong>{ticket.resolution_note || '未记录'}</p>}
      {ticket.status === 'open' && <div className="ticket-actions"><button className="primary-button small" disabled={loading === `ticket-${ticket.id}`} onClick={() => onUpdate(ticket.id, 'in_progress', '')}>{loading === `ticket-${ticket.id}` ? '更新中…' : '开始处理'}</button></div>}
      {ticket.status === 'in_progress' && <div className="ticket-complete"><textarea aria-label={`工单 ${ticket.id} 的解决说明`} rows={3} maxLength={2000} value={notes[ticket.id] ?? ''} placeholder="填写解决方法、验证结果或交付说明" onChange={(event) => setNotes((current) => ({ ...current, [ticket.id]: event.target.value }))} /><button className="primary-button small" disabled={!notes[ticket.id]?.trim() || loading === `ticket-${ticket.id}`} onClick={() => onUpdate(ticket.id, 'done', notes[ticket.id] ?? '')}>{loading === `ticket-${ticket.id}` ? '更新中…' : '标记完成'}</button></div>}
    </article>)}</div>}
  </section>
}
