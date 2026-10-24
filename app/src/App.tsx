import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { ApiError, request } from './api'
import { AnalysisInspector } from './components/AnalysisInspector'
import { EvaluationCenter } from './components/EvaluationCenter'
import { ModelSettings } from './components/ModelSettings'
import { DocumentsView, FeedbackView, Overview, TicketsView } from './components/ProjectViews'
import { Icon, Modal } from './components/Shared'
import type { Analysis, Document, Feedback, Health, Metrics, ModalKey, NavKey, Project, Ticket, Trace } from './types'
import { navItems } from './ui'

function App() {
  const [projects, setProjects] = useState<Project[]>([])
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null)
  const [documents, setDocuments] = useState<Document[]>([])
  const [feedback, setFeedback] = useState<Feedback[]>([])
  const [tickets, setTickets] = useState<Ticket[]>([])
  const [selectedFeedbackId, setSelectedFeedbackId] = useState<number | null>(null)
  const [analysis, setAnalysis] = useState<Analysis | null>(null)
  const [traces, setTraces] = useState<Trace[]>([])
  const [health, setHealth] = useState<Health | null>(null)
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [nav, setNav] = useState<NavKey>(() => navItems.find((item) => `#${item.key}` === window.location.hash)?.key ?? 'overview')
  const [search, setSearch] = useState('')
  const [feedbackSearch, setFeedbackSearch] = useState('')
  const [modal, setModal] = useState<ModalKey>(null)
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [projectLoading, setProjectLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [reviewConfirmed, setReviewConfirmed] = useState(false)
  const feedbackDetailRequest = useRef(0)
  const projectDataRequest = useRef(0)
  const pageTitle = useRef<HTMLHeadingElement>(null)

  useEffect(() => {
    window.history.replaceState(null, '', `#${nav}`)
    window.scrollTo(0, 0)
    pageTitle.current?.focus({ preventScroll: true })
  }, [nav])

  useEffect(() => {
    const syncNavigation = () => setNav(navItems.find((item) => `#${item.key}` === window.location.hash)?.key ?? 'overview')
    window.addEventListener('hashchange', syncNavigation)
    return () => window.removeEventListener('hashchange', syncNavigation)
  }, [])

  const activeProject = useMemo(() => projects.find((project) => project.id === activeProjectId) ?? null, [projects, activeProjectId])
  const selectedFeedback = useMemo(() => feedback.find((item) => item.id === selectedFeedbackId) ?? null, [feedback, selectedFeedbackId])

  const notify = useCallback((message: string) => {
    setToast(message)
    window.setTimeout(() => setToast(''), 3600)
  }, [])

  const loadProjectData = useCallback(async (projectId: number) => {
    const requestId = projectDataRequest.current + 1
    projectDataRequest.current = requestId
    feedbackDetailRequest.current += 1
    setReviewConfirmed(false)
    setProjectLoading(true)
    setError('')
    setSelectedFeedbackId(null)
    setAnalysis(null)
    setTraces([])
    try {
      const [nextDocuments, nextFeedback, nextTickets, nextMetrics] = await Promise.all([
        request<Document[]>(`/api/documents?project_id=${projectId}`),
        request<Feedback[]>(`/api/feedback?project_id=${projectId}`),
        request<Ticket[]>(`/api/tickets?project_id=${projectId}`),
        request<Metrics>(`/api/metrics?project_id=${projectId}`),
      ])
      if (requestId !== projectDataRequest.current) return
      setDocuments(nextDocuments)
      setFeedback(nextFeedback)
      setTickets(nextTickets)
      setMetrics(nextMetrics)
      setSelectedFeedbackId(nextFeedback[0]?.id ?? null)
    } catch (loadError) {
      if (requestId !== projectDataRequest.current) return
      setError(loadError instanceof Error ? loadError.message : '项目数据加载失败')
      setDocuments([])
      setFeedback([])
      setTickets([])
      setMetrics(null)
    } finally {
      if (requestId === projectDataRequest.current) setProjectLoading(false)
    }
  }, [])

  const loadFeedbackDetails = useCallback(async (feedbackId: number) => {
    const requestId = feedbackDetailRequest.current + 1
    feedbackDetailRequest.current = requestId
    setAnalysis(null)
    setTraces([])
    setReviewConfirmed(false)
    const [analysisResult, tracesResult] = await Promise.allSettled([
      request<Analysis>(`/api/feedback/${feedbackId}/analysis`),
      request<Trace[]>(`/api/traces?feedback_id=${feedbackId}`),
    ])
    if (requestId !== feedbackDetailRequest.current) return
    if (analysisResult.status === 'fulfilled') {
      setAnalysis(analysisResult.value)
    } else if (!(analysisResult.reason instanceof ApiError && analysisResult.reason.status === 404)) {
      setError(analysisResult.reason instanceof Error ? analysisResult.reason.message : '历史分析加载失败')
    }
    if (tracesResult.status === 'fulfilled') {
      setTraces(tracesResult.value)
    } else {
      setTraces([])
      if (tracesResult.reason instanceof Error) setError(tracesResult.reason.message)
    }
  }, [])

  const loadBootstrap = useCallback(async () => {
    setLoading(true)
    setError('')
    const [healthResult, projectsResult] = await Promise.allSettled([
      request<Health>('/api/health'),
      request<Project[]>('/api/projects'),
    ])
    if (healthResult.status === 'fulfilled') setHealth(healthResult.value)
    else setHealth(null)
    if (projectsResult.status === 'fulfilled') {
      setProjects(projectsResult.value)
      const savedId = Number(window.localStorage.getItem('feedback-workspace-project'))
      setActiveProjectId((current) => {
        const rows = projectsResult.value
        if (current !== null && rows.some((project) => project.id === current)) return current
        return rows.find((project) => project.id === savedId)?.id ?? rows[0]?.id ?? null
      })
    } else {
      const message = projectsResult.reason instanceof Error ? projectsResult.reason.message : '无法连接到后端服务'
      setError(message)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    const timeoutId = window.setTimeout(() => { void loadBootstrap() }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [loadBootstrap])

  useEffect(() => {
    if (activeProjectId === null) return undefined
    const timeoutId = window.setTimeout(() => { void loadProjectData(activeProjectId) }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [activeProjectId, loadProjectData])

  useEffect(() => {
    if (activeProjectId !== null) window.localStorage.setItem('feedback-workspace-project', String(activeProjectId))
  }, [activeProjectId])

  useEffect(() => {
    if (selectedFeedbackId === null) return undefined
    const timeoutId = window.setTimeout(() => { void loadFeedbackDetails(selectedFeedbackId) }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [selectedFeedbackId, loadFeedbackDetails])

  async function handleCreateProject(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (actionLoading) return
    setError('')
    const form = new FormData(event.currentTarget)
    const name = String(form.get('name') ?? '').trim()
    const description = String(form.get('description') ?? '').trim()
    if (!name) return
    setActionLoading('project')
    try {
      const created = await request<Project>('/api/projects', { method: 'POST', body: JSON.stringify({ name, description }) })
      setProjects((current) => [...current, created])
      setActiveProjectId(created.id)
      setModal(null)
      notify('项目已创建，可以开始添加资料和反馈')
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '项目创建失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleCreateDocument(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (actionLoading) return
    setError('')
    if (!activeProjectId) return
    const form = new FormData(event.currentTarget)
    const title = String(form.get('title') ?? '').trim()
    const content = String(form.get('content') ?? '').trim()
    if (!title || !content) return
    setActionLoading('document')
    try {
      const created = await request<Document>('/api/documents', { method: 'POST', body: JSON.stringify({ project_id: activeProjectId, title, content }) })
      setDocuments((current) => [created, ...current])
      setModal(null)
      notify('资料已加入当前项目')
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '资料添加失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleCreateFeedback(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (actionLoading) return
    setError('')
    if (!activeProjectId) return
    const form = new FormData(event.currentTarget)
    const source = String(form.get('source') ?? '').trim()
    const content = String(form.get('content') ?? '').trim()
    if (!source || !content) return
    setActionLoading('feedback')
    try {
      const created = await request<Feedback>('/api/feedback', { method: 'POST', body: JSON.stringify({ project_id: activeProjectId, source, content }) })
      setFeedback((current) => [created, ...current])
      setAnalysis(null)
      setTraces([])
      setReviewConfirmed(false)
      setSelectedFeedbackId(created.id)
      setNav('feedback')
      setModal(null)
      notify('反馈已进入待分析队列')
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '反馈提交失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleAnalyze() {
    if (!selectedFeedbackId || actionLoading) return
    feedbackDetailRequest.current += 1
    setActionLoading('analyze')
    setError('')
    setReviewConfirmed(false)
    try {
      const result = await request<Analysis>(`/api/feedback/${selectedFeedbackId}/analyze`, { method: 'POST' })
      setAnalysis(result)
      const nextTraces = await request<Trace[]>(`/api/traces?feedback_id=${selectedFeedbackId}`).catch(() => [])
      setTraces(nextTraces)
      if (activeProjectId) request<Metrics>(`/api/metrics?project_id=${activeProjectId}`).then(setMetrics).catch(() => undefined)
      setFeedback((current) => current.map((item) => item.id === selectedFeedbackId ? { ...item, status: 'analyzed' } : item))
      if (result.model_mode === 'unavailable') notify('分析未成功，请查看原因或执行记录后重试')
      else notify('分析已完成，请核对证据后决定是否建单')
    } catch (analyzeError) {
      setError(analyzeError instanceof Error ? analyzeError.message : '分析请求失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleApprove(title: string, reviewerNote: string) {
    if (!selectedFeedbackId || !reviewConfirmed || !title.trim() || !analysis?.proposed_task || !['ai', 'demo'].includes(analysis.model_mode)) return
    setActionLoading('approve')
    try {
      const created = await request<Ticket>(`/api/feedback/${selectedFeedbackId}/approve`, { method: 'POST', body: JSON.stringify({ title: title.trim(), reviewer_note: reviewerNote.trim() }) })
      setTickets((current) => current.some((ticket) => ticket.id === created.id) ? current : [created, ...current])
      setFeedback((current) => current.map((item) => item.id === selectedFeedbackId ? { ...item, status: 'ticketed' } : item))
      const nextTraces = await request<Trace[]>(`/api/traces?feedback_id=${selectedFeedbackId}`).catch(() => [])
      setTraces(nextTraces)
      if (activeProjectId) request<Metrics>(`/api/metrics?project_id=${activeProjectId}`).then(setMetrics).catch(() => undefined)
      setReviewConfirmed(false)
      notify('工单已创建，后续处理仍由团队确认')
    } catch (approveError) {
      setError(approveError instanceof Error ? approveError.message : '工单创建失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleUpdateTicket(ticketId: number, status: string, resolutionNote: string) {
    setActionLoading(`ticket-${ticketId}`)
    try {
      const updated = await request<Ticket>(`/api/tickets/${ticketId}`, { method: 'PATCH', body: JSON.stringify({ status, resolution_note: resolutionNote.trim() }) })
      setTickets((current) => current.map((ticket) => ticket.id === ticketId ? updated : ticket))
      if (activeProjectId) request<Metrics>(`/api/metrics?project_id=${activeProjectId}`).then(setMetrics).catch(() => undefined)
      notify(status === 'done' ? '工单已完成并记录解决说明' : '工单已进入处理中')
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : '工单状态更新失败')
    } finally {
      setActionLoading(null)
    }
  }

  function selectFeedback(id: number) {
    if (actionLoading) return
    feedbackDetailRequest.current += 1
    setAnalysis(null)
    setTraces([])
    setReviewConfirmed(false)
    setSelectedFeedbackId(id)
    if (nav === 'overview') setNav('feedback')
  }

  const pendingCount = feedback.filter((item) => !['ticket_created', 'ticketed', 'resolved'].includes(item.status)).length
  const aiReady = health?.ai_configured === true || health?.demo_mode === true
  const pageCopy = {
    overview: { title: '让每一条反馈，都有回响。', description: '汇集用户的声音，让洞察成为有依据、可追踪的下一步。', eyebrow: 'WORKSPACE OVERVIEW' },
    feedback: { title: '反馈收件箱', description: '从用户原话出发，找到问题背后的线索。', eyebrow: 'LISTEN · UNDERSTAND · RESPOND' },
    documents: { title: '产品资料库', description: '把产品知识整理好，让每一个回答都有据可循。', eyebrow: 'YOUR SINGLE SOURCE OF CONTEXT' },
    tickets: { title: '技术工单', description: '从确认问题到交付解决方案，让协作形成闭环。', eyebrow: 'FROM INSIGHT TO DELIVERY' },
    evaluations: { title: '评测中心', description: '让每一次改进，都有可复核的依据。', eyebrow: 'MEASURE · COMPARE · IMPROVE' },
  }[nav]
  const visibleFeedback = feedback.filter((item) => `${item.content} ${item.source}`.toLocaleLowerCase().includes(feedbackSearch.toLocaleLowerCase()))

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>跳到主要内容</a>
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Icon name="layers" size={23} /></div><div><strong>Signal<span className="brand-period">.</span></strong><small>反馈与工单工作台</small></div></div>
        <div className="workspace-switcher"><span className="project-dot"><Icon name="folder" size={18} /></span><label><span>当前项目空间</span><select disabled={Boolean(actionLoading)} aria-label="选择项目空间" value={activeProjectId ?? ''} onChange={(event) => setActiveProjectId(Number(event.target.value))}><option value="" disabled>{loading ? '正在加载…' : '请选择项目'}</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label></div>
        <div className="sidebar-label"><span>工作空间</span><span>WORKSPACE</span></div>
        <nav className="side-nav" aria-label="工作区导航">{navItems.map((item) => <button key={item.key} type="button" className={nav === item.key ? 'active' : ''} aria-current={nav === item.key ? 'page' : undefined} onClick={() => setNav(item.key)}><Icon name={item.icon} size={19} /><span>{item.label}</span>{item.key === 'feedback' && pendingCount > 0 && <span className="nav-count">{pendingCount}</span>}{item.key === 'evaluations' && <span className="nav-new">预览</span>}</button>)}</nav>
        <div className="sidebar-project-actions"><button type="button" className="new-project-button" onClick={() => setModal('project')}><Icon name="plus" size={16} />创建项目空间</button><button type="button" className="icon-button" disabled={Boolean(actionLoading)} aria-label="刷新项目列表" onClick={() => void loadBootstrap()}><Icon name="refresh" size={16} /></button></div>
        <div className="sidebar-bottom"><div className="sidebar-guide"><span className="guide-icon"><Icon name="shield" size={20} /></span><strong>AI 提建议，你做决定</strong><p>资料可追溯，工单经人工审核。<br />把每一步判断留在工作流里。</p><span className="guide-foot"><span className="status-pip" />HUMAN IN THE LOOP</span></div><div className="profile"><div className="avatar">本</div><div><strong>本地工作空间</strong><small>Local workspace</small></div><Icon name="shield" size={17} /></div></div>
      </aside>

      <div className="main-shell">
        <header className="topbar"><div className="breadcrumb"><Icon name="folder" size={16} /><span>{activeProject?.name ?? '工作空间'}</span><span className="crumb-slash">/</span><strong>{navItems.find((item) => item.key === nav)?.label}</strong></div><div className="topbar-actions"><form className="global-search" role="search" onSubmit={(event) => { event.preventDefault(); setFeedbackSearch(search.trim()); setNav('feedback') }}><Icon name="search" size={16} /><input aria-label="搜索反馈内容或来源" placeholder="搜索反馈…" value={search} onChange={(event) => setSearch(event.target.value)} /><button type="submit" aria-label="搜索反馈"><Icon name="arrow" size={15} /></button></form><button type="button" className="model-settings-trigger secondary-button" disabled={Boolean(actionLoading)} onClick={() => setModelSettingsOpen(true)}><Icon name="settings" size={16} />模型设置</button><div className={`service-status ${health ? (aiReady ? 'ready' : 'warning') : 'offline'}`}><span className="status-pip" />{health ? (health.demo_mode ? '离线固定回放' : aiReady ? 'AI 已配置' : 'AI 未配置') : '服务未连接'}</div></div></header>

        <main className="workspace" id="main-content" tabIndex={-1}>
          <div className="mobile-nav"><div className="mobile-project-bar"><strong>Signal.</strong><select disabled={Boolean(actionLoading)} className="mobile-project-select" aria-label="当前项目" value={activeProjectId ?? ''} onChange={(event) => setActiveProjectId(Number(event.target.value))}><option value="" disabled>选择项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><button type="button" className="icon-button" aria-label="创建项目" onClick={() => setModal('project')}><Icon name="plus" size={18} /></button></div><nav aria-label="移动工作区导航">{navItems.map((item) => <button type="button" key={item.key} aria-current={nav === item.key ? 'page' : undefined} className={nav === item.key ? 'active' : ''} onClick={() => setNav(item.key)}><Icon name={item.icon} size={18} /><span>{item.label.replace('工作台总览', '总览').replace('反馈收件箱', '反馈').replace('产品资料库', '资料').replace('技术工单', '工单').replace('评测中心', '评测')}</span></button>)}</nav></div>
          {health?.demo_mode && <div className="error-banner" role="status"><Icon name="info" size={17} /><span>离线演示 · 使用固定题集回放，不调用模型。仅支持预置问题，数据保存在独立演示库。</span></div>}<section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-mark" />{pageCopy.eyebrow}</div><h1 ref={pageTitle} tabIndex={-1}>{pageCopy.title}</h1><p>{pageCopy.description}</p></div>{nav !== 'evaluations' && activeProject && <div className="page-actions"><button type="button" className="secondary-button" onClick={() => setModal('document')}><Icon name="book" size={16} />添加资料</button><button type="button" className="primary-button" onClick={() => setModal('feedback')}><Icon name="plus" size={16} />录入反馈</button></div>}</section>
          {error && <div className="error-banner" role="alert"><Icon name="alert" size={17} /><span>{error}</span><button type="button" className="text-button" disabled={Boolean(actionLoading)} onClick={() => void loadBootstrap()}>重新连接</button><button type="button" className="icon-button" onClick={() => setError('')} aria-label="关闭提示"><Icon name="close" size={16} /></button></div>}
          {nav === 'evaluations' ? <EvaluationCenter /> : loading || projectLoading ? <div className="workspace-loading" role="status"><div className="loading-line"><span />正在同步项目数据…</div><div className="skeleton-grid">{[1, 2, 3, 4].map((item) => <div className="skeleton-card" key={item} />)}</div></div> : !activeProject ? <div className="no-project panel"><div className="no-project-art"><Icon name="layers" size={32} /></div><span className="panel-eyebrow">A PLACE FOR EVERY SIGNAL</span><h2>从一个项目空间开始</h2><p>把产品资料、用户反馈和处理进展放在一起，<br />让每一个问题都能找到下一步。</p><button type="button" className="primary-button" onClick={() => setModal('project')}><Icon name="plus" size={17} />创建第一个项目</button><button type="button" className="text-button" onClick={() => setNav('evaluations')}>先看看历史评测<Icon name="arrow" size={15} /></button></div> : <>
            {nav === 'overview' && <Overview documents={documents} feedback={feedback} tickets={tickets} metrics={metrics} selectedFeedbackId={selectedFeedbackId} onSelectFeedback={selectFeedback} onAddFeedback={() => setModal('feedback')} onAddDocument={() => setModal('document')} onOpenFeedback={() => setNav('feedback')} onOpenEvaluations={() => setNav('evaluations')} />}
            {nav === 'documents' && <DocumentsView documents={documents} onAdd={() => setModal('document')} />}
            {nav === 'feedback' && <><div className="inbox-search"><Icon name="search" size={17} /><input aria-label="筛选反馈" placeholder="搜索用户原话、反馈来源…" value={feedbackSearch} onChange={(event) => setFeedbackSearch(event.target.value)} />{feedbackSearch && <button type="button" className="icon-button" aria-label="清除搜索" onClick={() => { setFeedbackSearch(''); setSearch('') }}><Icon name="close" size={16} /></button>}<span>{visibleFeedback.length} 条反馈</span></div><FeedbackView feedback={visibleFeedback} selectedFeedbackId={selectedFeedbackId} onSelect={selectFeedback} onAdd={() => setModal('feedback')} filtered={Boolean(feedbackSearch)} /></>}
            {nav === 'tickets' && <TicketsView tickets={tickets} feedback={feedback} onUpdate={(id, status, note) => void handleUpdateTicket(id, status, note)} loading={actionLoading} />}
            {nav === 'feedback' && selectedFeedback && visibleFeedback.some((item) => item.id === selectedFeedback.id) && <AnalysisInspector key={`${selectedFeedback.id}:${analysis?.proposed_task ?? ''}`} feedback={selectedFeedback} analysis={analysis} traces={traces} reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed} onAnalyze={() => void handleAnalyze()} onApprove={(title, note) => void handleApprove(title, note)} loading={actionLoading} aiConfigured={aiReady} demoMode={health?.demo_mode === true} />}
          </>}
        </main>
        <footer className="footer"><span><span className="footer-brand">Signal.</span> 每一个反馈，都值得被认真对待。</span><span><Icon name="shield" size={13} />项目资料隔离 · 人工审核</span></footer>
      </div>

      {modal && <Modal title={modal === 'project' ? '创建项目空间' : modal === 'document' ? '添加产品资料' : '录入用户反馈'} description={modal === 'project' ? '每个项目拥有独立的资料、反馈与工单。' : modal === 'document' ? '只添加你确认可以使用的产品资料，AI 只会引用当前项目内容。' : '保留用户原话，方便之后核对 AI 的判断依据。'} onClose={() => setModal(null)}><form className="modal-form" onSubmit={modal === 'project' ? handleCreateProject : modal === 'document' ? handleCreateDocument : handleCreateFeedback}>{error && <div className="error-banner" role="alert">{error}</div>}{modal === 'project' && <><label>项目名称<input name="name" maxLength={120} placeholder="例如：一按即定 · 用户反馈" autoFocus required /></label><label>项目描述<textarea name="description" maxLength={2000} rows={3} placeholder="说明这个项目服务的产品或场景" /></label></>}{modal === 'document' && <><label>资料标题<input name="title" maxLength={200} placeholder="例如：小程序使用说明 v1.2" autoFocus required /></label><label>资料正文<textarea name="content" maxLength={100000} rows={8} placeholder="粘贴产品说明、版本记录、常见问题或接口约定…" required /></label></>}{modal === 'feedback' && <><label>反馈来源<input name="source" maxLength={100} placeholder="例如：微信用户 / 测试同学 / 体验记录" autoFocus required /></label><label>反馈内容<textarea name="content" maxLength={20000} rows={8} placeholder="记录用户遇到的问题、复现步骤或期望…" required /></label></>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button type="submit" className="primary-button" disabled={actionLoading === modal}>{actionLoading === modal ? '保存中…' : '保存并继续'}</button></div></form></Modal>}
      {modelSettingsOpen && <ModelSettings onClose={() => setModelSettingsOpen(false)} onChanged={async () => {
        setHealth(await request<Health>('/api/health'))
        setReviewConfirmed(false)
        if (selectedFeedbackId) await loadFeedbackDetails(selectedFeedbackId)
      }} />}
      {toast && <div className="toast" role="status"><span className="toast-check"><Icon name="check" size={14} /></span>{toast}</div>}
    </div>
  )
}

export default App
