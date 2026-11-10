import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import './App.css'
import { ApiError, request } from './api'
import { AnalysisInspector } from './components/AnalysisInspector'
import { ModelSettings } from './components/ModelSettings'
import { DocumentsView, FeedbackView, Overview, TicketsView } from './components/ProjectViews'
import { Icon, Modal } from './components/Shared'
import type { Analysis, Document, Feedback, Health, Metrics, ModalKey, NavKey, Project, Ticket, Trace } from './types'
import { formatDate, navItems } from './ui'

const EvaluationCenter = lazy(async () => ({ default: (await import('./components/EvaluationCenter')).EvaluationCenter }))
const inboxFilters = [
  { key: 'all', label: '全部' },
  { key: 'new', label: '待分析' },
  { key: 'analyzed', label: '待复核' },
  { key: 'ticketed', label: '已建单' },
] as const
type InboxFilter = typeof inboxFilters[number]['key']

function matchesInboxFilter(item: Feedback, filter: InboxFilter) {
  if (filter === 'all') return true
  if (filter === 'new') return ['new', 'pending'].includes(item.status)
  if (filter === 'analyzed') return ['analyzed', 'in_review'].includes(item.status)
  return ['ticket_created', 'ticketed', 'resolved'].includes(item.status)
}

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
  const [inboxFilter, setInboxFilter] = useState<InboxFilter>('all')
  const [openDocument, setOpenDocument] = useState<Document | null>(null)
  const [focusedTicketId, setFocusedTicketId] = useState<number | null>(null)
  const [modal, setModal] = useState<ModalKey>(null)
  const [modelSettingsOpen, setModelSettingsOpen] = useState(false)
  const [loading, setLoading] = useState(true)
  const [projectLoading, setProjectLoading] = useState(false)
  const [detailsLoading, setDetailsLoading] = useState(false)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [error, setError] = useState('')
  const [toast, setToast] = useState('')
  const [reviewConfirmed, setReviewConfirmed] = useState(false)
  const selectedFeedbackRef = useRef<number | null>(null)
  const feedbackDetailRequest = useRef(0)
  const projectDataRequest = useRef(0)
  const metricsRequest = useRef(0)
  const toastTimer = useRef<number>(undefined)
  const pageTitle = useRef<HTMLHeadingElement>(null)
  const inspector = useRef<HTMLDivElement>(null)

  useEffect(() => {
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
  const selectedTicket = tickets.find((ticket) => ticket.feedback_id === selectedFeedbackId)

  function navigate(next: NavKey) {
    if (next === nav) return
    window.history.pushState(null, '', `#${next}`)
    setNav(next)
  }

  const notify = useCallback((message: string) => {
    window.clearTimeout(toastTimer.current)
    setToast(message)
    toastTimer.current = window.setTimeout(() => setToast(''), 3600)
  }, [])
  useEffect(() => () => window.clearTimeout(toastTimer.current), [])

  const setSelection = useCallback((id: number | null) => {
    selectedFeedbackRef.current = id
    setSelectedFeedbackId(id)
  }, [])

  const loadProjectData = useCallback(async (projectId: number) => {
    const requestId = projectDataRequest.current + 1
    projectDataRequest.current = requestId
    feedbackDetailRequest.current += 1
    setReviewConfirmed(false)
    setProjectLoading(true)
    setError('')
    setDetailsLoading(true)
    setAnalysis(null)
    setTraces([])
    try {
      const [nextDocuments, nextFeedback, nextTickets, nextMetrics] = await Promise.all([
        request<Document[]>(`/api/documents?project_id=${projectId}`),
        request<Feedback[]>(`/api/feedback?project_id=${projectId}`),
        request<Ticket[]>(`/api/tickets?project_id=${projectId}`),
        request<Metrics>(`/api/metrics?project_id=${projectId}`).catch(() => null),
      ])
      if (requestId !== projectDataRequest.current) return
      setDocuments(nextDocuments)
      setFeedback(nextFeedback)
      setTickets(nextTickets)
      setMetrics(nextMetrics)
      const current = selectedFeedbackRef.current
      setSelection(nextFeedback.some((item) => item.id === current) ? current : nextFeedback[0]?.id ?? null)
    } catch (loadError) {
      if (requestId !== projectDataRequest.current) return
      setError(loadError instanceof Error ? loadError.message : '项目数据加载失败')
      setDocuments([])
      setFeedback([])
      setSelection(null)
      setTickets([])
      setMetrics(null)
    } finally {
      if (requestId === projectDataRequest.current) setProjectLoading(false)
    }
  }, [setSelection])

  const loadFeedbackDetails = useCallback(async (feedbackId: number) => {
    const requestId = feedbackDetailRequest.current + 1
    feedbackDetailRequest.current = requestId
    setAnalysis(null)
    setTraces([])
    setReviewConfirmed(false)
    setDetailsLoading(true)
    const [analysisResult, tracesResult] = await Promise.allSettled([
      request<Analysis>(`/api/feedback/${feedbackId}/analysis`),
      request<Trace[]>(`/api/traces?feedback_id=${feedbackId}`),
    ])
    if (requestId !== feedbackDetailRequest.current) return
    setDetailsLoading(false)
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

  const loadBootstrap = useCallback(async (refreshProjectId?: number | null) => {
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
      let savedId: number | null = null
      try { savedId = Number(window.localStorage.getItem('feedback-workspace-project')) } catch { /* Storage may be disabled. */ }
      setActiveProjectId((current) => {
        const rows = projectsResult.value
        if (current !== null && rows.some((project) => project.id === current)) return current
        return rows.find((project) => project.id === savedId)?.id ?? rows[0]?.id ?? null
      })
      if (refreshProjectId && projectsResult.value.some((project) => project.id === refreshProjectId)) {
        await loadProjectData(refreshProjectId)
      }
    } else {
      const message = projectsResult.reason instanceof Error ? projectsResult.reason.message : '无法连接到后端服务'
      setError(message)
    }
    setLoading(false)
  }, [loadProjectData])

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
    if (activeProjectId === null) return
    try { window.localStorage.setItem('feedback-workspace-project', String(activeProjectId)) } catch { /* Storage may be disabled. */ }
  }, [activeProjectId])

  useEffect(() => {
    if (selectedFeedbackId === null || projectLoading) return undefined
    const timeoutId = window.setTimeout(() => { void loadFeedbackDetails(selectedFeedbackId) }, 0)
    return () => window.clearTimeout(timeoutId)
  }, [selectedFeedbackId, projectLoading, loadFeedbackDetails])

  function switchProject(id: number) {
    if (id === activeProjectId) return
    projectDataRequest.current += 1
    feedbackDetailRequest.current += 1
    setProjectLoading(true)
    setSelection(null)
    setOpenDocument(null)
    setFocusedTicketId(null)
    resetInbox()
    setActiveProjectId(id)
  }

  function resetInbox() {
    setInboxFilter('all')
    setFeedbackSearch('')
    setSearch('')
  }

  function refreshMetrics() {
    if (!activeProjectId) return
    const projectVersion = projectDataRequest.current
    const version = ++metricsRequest.current
    void request<Metrics>(`/api/metrics?project_id=${activeProjectId}`).then((next) => {
      if (projectVersion === projectDataRequest.current && version === metricsRequest.current) setMetrics(next)
    }).catch(() => undefined)
  }

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
      setProjects((current) => [created, ...current])
      switchProject(created.id)
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
      refreshMetrics()
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
      resetInbox()
      openFeedback(created.id)
      refreshMetrics()
      setModal(null)
      notify('反馈已进入待分析队列')
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : '反馈提交失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleAnalyze() {
    if (!selectedFeedbackId || actionLoading || detailsLoading || selectedTicket) return
    const detailVersion = ++feedbackDetailRequest.current
    setActionLoading(`analyze-${selectedFeedbackId}`)
    setError('')
    setReviewConfirmed(false)
    try {
      const result = await request<Analysis>(`/api/feedback/${selectedFeedbackId}/analyze`, { method: 'POST' })
      setFeedback((current) => current.map((item) => item.id === selectedFeedbackId && item.status === 'new' ? { ...item, status: 'analyzed' } : item))
      refreshMetrics()
      if (selectedFeedbackRef.current === selectedFeedbackId) {
        const resultVersion = ++feedbackDetailRequest.current
        setDetailsLoading(false)
        setAnalysis(result)
        setInboxFilter((current) => current === 'new' ? 'all' : current)
        const nextTraces = await request<Trace[]>(`/api/traces?feedback_id=${selectedFeedbackId}`).catch(() => [])
        if (resultVersion === feedbackDetailRequest.current) setTraces(nextTraces)
      }
      if (result.model_mode === 'unavailable') notify('分析未成功，请查看原因或执行记录后重试')
      else notify('分析已完成，请核对证据后决定是否建单')
    } catch (analyzeError) {
      if (detailVersion === feedbackDetailRequest.current && activeProjectId && analyzeError instanceof ApiError && [0, 409].includes(analyzeError.status)) {
        await loadProjectData(activeProjectId)
      }
      setError(analyzeError instanceof Error ? analyzeError.message : '分析请求失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleApprove(title: string, reviewerNote: string) {
    if (actionLoading || detailsLoading || !selectedFeedbackId || selectedTicket || !reviewConfirmed || !title.trim() || !analysis?.proposed_task) return
    if (analysis.feedback_id !== selectedFeedbackId || (analysis.model_mode !== 'ai' && !(analysis.model_mode === 'demo' && health?.demo_mode))) return
    const detailVersion = feedbackDetailRequest.current
    setError('')
    setActionLoading(`approve-${selectedFeedbackId}`)
    try {
      const created = await request<Ticket>(`/api/feedback/${selectedFeedbackId}/approve`, {
        method: 'POST',
        body: JSON.stringify({ title: title.trim(), reviewer_note: reviewerNote.trim(), analysis_updated_at: analysis.updated_at || undefined }),
      })
      setTickets((current) => current.some((ticket) => ticket.id === created.id) ? current : [created, ...current])
      setFeedback((current) => current.map((item) => item.id === selectedFeedbackId ? { ...item, status: 'ticketed' } : item))
      if (selectedFeedbackRef.current === selectedFeedbackId) {
        setInboxFilter('all')
        void loadFeedbackDetails(selectedFeedbackId)
      }
      refreshMetrics()
      notify('工单已创建，可从反馈查看进度')
    } catch (approveError) {
      if (detailVersion === feedbackDetailRequest.current && activeProjectId && approveError instanceof ApiError && [0, 409].includes(approveError.status)) {
        await loadProjectData(activeProjectId)
      }
      setError(approveError instanceof Error ? approveError.message : '工单创建失败')
    } finally {
      setActionLoading(null)
    }
  }

  async function handleUpdateTicket(ticketId: number, status: string, resolutionNote: string) {
    if (actionLoading) return
    setError('')
    setActionLoading(`ticket-${ticketId}`)
    try {
      const updated = await request<Ticket>(`/api/tickets/${ticketId}`, { method: 'PATCH', body: JSON.stringify({ status, resolution_note: resolutionNote.trim() }) })
      setTickets((current) => current.map((ticket) => ticket.id === ticketId ? updated : ticket))
      refreshMetrics()
      if (updated.feedback_id === selectedFeedbackRef.current) void loadFeedbackDetails(updated.feedback_id)
      notify(status === 'done' ? '工单已完成并记录解决说明' : '工单已进入处理中')
    } catch (updateError) {
      setError(updateError instanceof Error ? updateError.message : '工单状态更新失败')
    } finally {
      setActionLoading(null)
    }
  }

  function openFeedback(id: number) {
    if (id !== selectedFeedbackRef.current) {
      feedbackDetailRequest.current += 1
      setAnalysis(null)
      setTraces([])
      setReviewConfirmed(false)
      setDetailsLoading(true)
      setSelection(id)
    }
    navigate('feedback')
  }

  function selectInboxRow(id: number) {
    openFeedback(id)
    if (window.matchMedia('(max-width: 980px)').matches) {
      inspector.current?.focus({ preventScroll: true })
      inspector.current?.scrollIntoView({ block: 'start' })
    }
  }

  function openTicket(id: number) {
    setFocusedTicketId(id)
    navigate('tickets')
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
  const query = feedbackSearch.trim().toLocaleLowerCase()
  const visibleFeedback = feedback.filter((item) => matchesInboxFilter(item, inboxFilter) &&
    `${item.source} ${item.content} FB-${String(item.id).padStart(4, '0')}`.toLocaleLowerCase().includes(query))
  const visibleSelection = selectedFeedback && visibleFeedback.some((item) => item.id === selectedFeedback.id) ? selectedFeedback : null
  const blocked = Boolean(loading || projectLoading || actionLoading)

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content" onClick={(event) => { event.preventDefault(); document.getElementById('main-content')?.focus() }}>跳到主要内容</a>
      <aside className="sidebar">
        <div className="brand"><div className="brand-mark"><Icon name="layers" size={23} /></div><div><strong>Signal<span className="brand-period">.</span></strong><small>反馈与工单工作台</small></div></div>
        <div className="workspace-switcher"><span className="project-dot"><Icon name="folder" size={18} /></span><label><span>当前项目空间</span><select disabled={blocked} aria-label="选择项目空间" value={activeProjectId ?? ''} onChange={(event) => switchProject(Number(event.target.value))}><option value="" disabled>{loading ? '正在加载…' : '请选择项目'}</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label></div>
        <div className="sidebar-label"><span>工作空间</span><span>WORKSPACE</span></div>
        <nav className="side-nav" aria-label="工作区导航">{navItems.map((item) => <button key={item.key} type="button" className={nav === item.key ? 'active' : ''} aria-current={nav === item.key ? 'page' : undefined} onClick={() => navigate(item.key)}><Icon name={item.icon} size={19} /><span>{item.label}</span>{item.key === 'feedback' && pendingCount > 0 && <span className="nav-count">{pendingCount}</span>}{item.key === 'evaluations' && <span className="nav-new">预览</span>}</button>)}</nav>
        <div className="sidebar-project-actions"><button type="button" className="new-project-button" onClick={() => setModal('project')}><Icon name="plus" size={16} />创建项目空间</button><button type="button" className="icon-button" disabled={blocked} aria-label="刷新项目列表" onClick={() => void loadBootstrap(activeProjectId)}><Icon name="refresh" size={16} /></button></div>
        <div className="sidebar-bottom"><div className="sidebar-guide"><span className="guide-icon"><Icon name="shield" size={20} /></span><strong>AI 提建议，你做决定</strong><p>资料可追溯，工单经人工审核。<br />把每一步判断留在工作流里。</p><span className="guide-foot"><span className="status-pip" />HUMAN IN THE LOOP</span></div><div className="profile"><div className="avatar">本</div><div><strong>本地工作空间</strong><small>Local workspace</small></div><Icon name="shield" size={17} /></div></div>
      </aside>

      <div className="main-shell">
        <header className="topbar"><div className="breadcrumb"><Icon name="folder" size={16} /><span>{activeProject?.name ?? '工作空间'}</span><span className="crumb-slash">/</span><strong>{navItems.find((item) => item.key === nav)?.label}</strong></div><div className="topbar-actions"><form className="global-search" role="search" onSubmit={(event) => { event.preventDefault(); setFeedbackSearch(search.trim()); setInboxFilter('all'); navigate('feedback') }}><Icon name="search" size={16} /><input aria-label="搜索反馈内容或来源" placeholder="搜索反馈…" value={search} onChange={(event) => setSearch(event.target.value)} /><button type="submit" aria-label="搜索反馈"><Icon name="arrow" size={15} /></button></form><button type="button" className="model-settings-trigger secondary-button" disabled={blocked} onClick={() => setModelSettingsOpen(true)}><Icon name="settings" size={16} />模型设置</button><div className={`service-status ${health ? (aiReady ? 'ready' : 'warning') : 'offline'}`}><span className="status-pip" />{health ? (health.demo_mode ? '离线固定回放' : aiReady ? 'AI 已配置' : 'AI 未配置') : '服务未连接'}</div></div></header>

        <main className="workspace" id="main-content" tabIndex={-1}>
          <div className="mobile-nav"><div className="mobile-project-bar"><strong>Signal.</strong><select disabled={blocked} className="mobile-project-select" aria-label="当前项目" value={activeProjectId ?? ''} onChange={(event) => switchProject(Number(event.target.value))}><option value="" disabled>选择项目</option>{projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select><button type="button" className="icon-button" aria-label="创建项目" onClick={() => setModal('project')}><Icon name="plus" size={18} /></button></div><nav aria-label="移动工作区导航">{navItems.map((item) => <button type="button" key={item.key} aria-current={nav === item.key ? 'page' : undefined} className={nav === item.key ? 'active' : ''} onClick={() => navigate(item.key)}><Icon name={item.icon} size={18} /><span>{item.label.replace('工作台总览', '总览').replace('反馈收件箱', '反馈').replace('产品资料库', '资料').replace('技术工单', '工单').replace('评测中心', '评测')}</span></button>)}</nav></div>
          {health?.demo_mode && <div className="error-banner" role="status"><Icon name="info" size={17} /><span>离线演示 · 使用固定题集回放，不调用模型。仅支持预置问题，数据保存在独立演示库。</span></div>}<section className="page-heading"><div><div className="eyebrow"><span className="eyebrow-mark" />{pageCopy.eyebrow}</div><h1 ref={pageTitle} tabIndex={-1}>{pageCopy.title}</h1><p>{pageCopy.description}</p></div>{nav !== 'evaluations' && activeProject && !loading && !projectLoading && <div className="page-actions"><button type="button" className="secondary-button" onClick={() => setModal('document')}><Icon name="book" size={16} />添加资料</button><button type="button" className="primary-button" onClick={() => setModal('feedback')}><Icon name="plus" size={16} />录入反馈</button></div>}</section>
          {error && <div className="error-banner" role="alert"><Icon name="alert" size={17} /><span>{error}</span><button type="button" className="text-button" disabled={blocked} onClick={() => void loadBootstrap(activeProjectId)}>重新连接</button><button type="button" className="icon-button" onClick={() => setError('')} aria-label="关闭提示"><Icon name="close" size={16} /></button></div>}
          {nav === 'evaluations' ? <Suspense fallback={<div className="workspace-loading" role="status">正在打开评测中心…</div>}><EvaluationCenter /></Suspense> : loading || projectLoading ? <div className="workspace-loading" role="status"><div className="loading-line"><span />正在同步项目数据…</div><div className="skeleton-grid">{[1, 2, 3, 4].map((item) => <div className="skeleton-card" key={item} />)}</div></div> : !activeProject ? <div className="no-project panel"><div className="no-project-art"><Icon name="layers" size={32} /></div><span className="panel-eyebrow">A PLACE FOR EVERY SIGNAL</span><h2>从一个项目空间开始</h2><p>把产品资料、用户反馈和处理进展放在一起，<br />让每一个问题都能找到下一步。</p><button type="button" className="primary-button" onClick={() => setModal('project')}><Icon name="plus" size={17} />创建第一个项目</button><button type="button" className="text-button" onClick={() => navigate('evaluations')}>先看看历史评测<Icon name="arrow" size={15} /></button></div> : <>
            {nav === 'overview' && <Overview documents={documents} feedback={feedback} tickets={tickets} metrics={metrics}
              selectedFeedbackId={selectedFeedbackId} onSelectFeedback={(id) => { resetInbox(); openFeedback(id) }}
              onAddFeedback={() => setModal('feedback')} onAddDocument={() => setModal('document')}
              onOpenFeedback={() => navigate('feedback')} onOpenEvaluations={() => navigate('evaluations')} />}
            {nav === 'documents' && <DocumentsView key={activeProject.id} documents={documents}
              onAdd={() => setModal('document')} onOpen={setOpenDocument} />}
            {nav === 'feedback' && <div className="inbox-workbench">
              <FeedbackView feedback={visibleFeedback} selectedFeedbackId={visibleSelection?.id ?? null} onSelect={selectInboxRow}
                onAdd={() => setModal('feedback')} filtered={Boolean(query) || inboxFilter !== 'all'} onReset={resetInbox}>
                <div className="inbox-search">
                  <Icon name="search" size={17} />
                  <input type="search" aria-label="筛选反馈" placeholder="搜索原话、来源或编号" value={feedbackSearch}
                    onChange={(event) => { setFeedbackSearch(event.target.value); setSearch(event.target.value) }} />
                </div>
                <div className="inbox-filters" role="group" aria-label="按状态筛选反馈">
                  {inboxFilters.map(({ key, label }) => <button key={key} type="button" aria-pressed={inboxFilter === key}
                    onClick={() => setInboxFilter(key)}>{label}</button>)}
                </div>
              </FeedbackView>
              <div className="inbox-detail" id="inbox-detail" tabIndex={-1} ref={inspector}>
                {visibleSelection ? <AnalysisInspector key={`${visibleSelection.id}:${analysis?.updated_at ?? ''}`}
                  feedback={visibleSelection} analysis={analysis} traces={traces} ticket={selectedTicket}
                  reviewConfirmed={reviewConfirmed} setReviewConfirmed={setReviewConfirmed}
                  onAnalyze={() => void handleAnalyze()} onApprove={(title, note) => void handleApprove(title, note)}
                  onOpenTicket={openTicket} onOpenDocument={(id) => setOpenDocument(documents.find((item) => item.id === id) ?? null)}
                  onOpenSettings={() => setModelSettingsOpen(true)} documentIds={documents.map((item) => item.id)}
                  loading={actionLoading} detailsLoading={detailsLoading} aiConfigured={aiReady} demoMode={health?.demo_mode === true} />
                  : <section className="panel inbox-placeholder"><Icon name="inbox" size={24} /><h2>选择一条反馈</h2><p>查看用户原话、处理建议、证据和工单进度。</p></section>}
              </div>
            </div>}
            {nav === 'tickets' && <TicketsView key={activeProject.id} tickets={tickets} feedback={feedback} focusedTicketId={focusedTicketId}
              onOpenFeedback={(id) => { resetInbox(); openFeedback(id) }}
              onUpdate={(id, status, note) => void handleUpdateTicket(id, status, note)} loading={actionLoading} />}
          </>}
        </main>
        <footer className="footer"><span><span className="footer-brand">Signal.</span> 每一个反馈，都值得被认真对待。</span><span><Icon name="shield" size={13} />项目资料隔离 · 人工审核</span></footer>
      </div>

      {modal && <Modal title={modal === 'project' ? '创建项目空间' : modal === 'document' ? '添加产品资料' : '录入用户反馈'} description={modal === 'project' ? '每个项目拥有独立的资料、反馈与工单。' : modal === 'document' ? '只添加你确认可以使用的产品资料，AI 只会引用当前项目内容。' : '保留用户原话，方便之后核对 AI 的判断依据。'} onClose={() => setModal(null)}><form className="modal-form" onSubmit={modal === 'project' ? handleCreateProject : modal === 'document' ? handleCreateDocument : handleCreateFeedback}>{error && <div className="error-banner" role="alert">{error}</div>}{modal === 'project' && <><label>项目名称<input name="name" maxLength={120} placeholder="例如：一按即定 · 用户反馈" autoFocus required /></label><label>项目描述<textarea name="description" maxLength={2000} rows={3} placeholder="说明这个项目服务的产品或场景" /></label></>}{modal === 'document' && <><label>资料标题<input name="title" maxLength={200} placeholder="例如：小程序使用说明 v1.2" autoFocus required /></label><label>资料正文<textarea name="content" maxLength={100000} rows={8} placeholder="粘贴产品说明、版本记录、常见问题或接口约定…" required /></label></>}{modal === 'feedback' && <><label>反馈来源<input name="source" maxLength={100} placeholder="例如：微信用户 / 测试同学 / 体验记录" autoFocus required /></label><label>反馈内容<textarea name="content" maxLength={20000} rows={8} placeholder="记录用户遇到的问题、复现步骤或期望…" required /></label></>}<div className="modal-actions"><button type="button" className="secondary-button" onClick={() => setModal(null)}>取消</button><button type="submit" className="primary-button" disabled={blocked}>{actionLoading === modal ? '保存中…' : '保存并继续'}</button></div></form></Modal>}
      {openDocument && <Modal title={openDocument.title} description={`DOC-${String(openDocument.id).padStart(3, '0')} · ${formatDate(openDocument.created_at)}`} onClose={() => setOpenDocument(null)}>
        <div className="document-reader">{openDocument.content}</div>
      </Modal>}
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
