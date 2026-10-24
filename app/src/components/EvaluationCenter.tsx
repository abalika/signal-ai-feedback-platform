import { useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
import fixtureRaw from '../../../examples/eval_cases.json?raw'
import summaryRaw from '../../../examples/eval_summary_2026-09-16.json?raw'
import retrievalRaw from '../../../examples/retrieval_eval_summary.json?raw'
import liveReportUrl from '../../../docs/reports/live-retest-20261021.html?url'
import { EmptyState, Icon, MetricCard, Modal, PanelHeader } from './Shared'

type EvalCase = { id: string; kind: string; question: string; reference_answer: string; expected_document?: string }
type RetrievalMetrics = { algorithm: string; cases: number; recall_at_1: number; recall_at_3: number; mrr: number }
const fixture = JSON.parse(fixtureRaw) as { cases: EvalCase[] }
const summary = JSON.parse(summaryRaw) as {
  evaluated_at: string; model: string; run_scope: { total: number; answerable: number; deliberately_unanswerable: number }
  system_result: { model_mode_ai: number; model_mode_unavailable: number }
  manual_review: { answerable_core_answer_matches_reference: number; unanswerable_did_not_invent_requested_value_or_event: number }
}
const retrieval = JSON.parse(retrievalRaw) as {
  scope: { documents: number; note: string }; baseline: RetrievalMetrics; current: RetrievalMetrics
  cases: { case_id: string; baseline_rank: number; current_rank: number; expected_document: string }[]
}
const percent = (value: number) => `${(value * 100).toFixed(value === 1 ? 0 : 2)}%`

function exportSnapshot() {
  const blob = new Blob([JSON.stringify({ source: 'Repository historical snapshots; not a new evaluation run', summary, retrieval }, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `signal-evaluation-history-${summary.evaluated_at}.json`
  link.click()
  window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function EvaluationCenter() {
  const [tab, setTab] = useState<'report' | 'cases'>('report')
  const [filter, setFilter] = useState('all')
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<EvalCase | null>(null)
  const visible = useMemo(() => fixture.cases.filter((item) => (filter === 'all' || (filter === 'answerable' ? Boolean(item.expected_document) : !item.expected_document)) && `${item.id} ${item.question} ${item.reference_answer}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())), [filter, query])
  const manual = summary.manual_review
  const reviewed = manual.answerable_core_answer_matches_reference + manual.unanswerable_did_not_invent_requested_value_or_event
  const selectedRetrieval = retrieval.cases.find((item) => item.case_id === selected?.id)
  function handleTabKey(event: KeyboardEvent<HTMLButtonElement>) {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const next = event.key === 'Home' ? 'report' : event.key === 'End' ? 'cases' : tab === 'report' ? 'cases' : 'report'
    setTab(next)
    document.getElementById(`${next}-tab`)?.focus()
  }

  return <div className="evaluation-center">
    <div className="evaluation-toolbar"><span className="snapshot-label"><Icon name="clock" size={15} /><span>历史评测快照</span><span className="toolbar-separator" /><span className="snapshot-project">一按即定 · 固定题集</span></span><button className="secondary-button" type="button" onClick={exportSnapshot}><Icon name="download" size={16} />导出历史报告</button></div>
    <section className="eval-hero">
      <div className="eval-hero-copy"><span className="hero-kicker"><span className="status-pip" />EVALUATION BASELINE</span><h2>每一次迭代，都看得见。</h2><p>从回答质量到检索命中，<br />为更可靠的 AI，建立一把自己的尺子。</p><div className="hero-meta"><span><Icon name="clock" size={14} />{summary.evaluated_at}</span><span><Icon name="layers" size={14} />{summary.run_scope.total} 条固定样本</span><span className="hero-meta-review">人工核对</span></div></div>
      <div className="eval-hero-result"><div className="baseline-orbit"><div><span>历史人工核对</span><strong>{reviewed}<small> / {summary.run_scope.total}</small></strong><span>符合报告中的核对项</span></div></div><span className="hero-result-caption"><Icon name="shield" size={14} />单次固定集回归 · 非生产准确率</span></div>
    </section>
    <div className="snapshot-notice"><Icon name="info" size={17} /><p>此页展示 2026-09-16 历史基线。2026-10-21 已追加真实复测：36 条分析可用，辅助复核 35 条符合参考、1 条待确认。最新逐题证据见下方报告；30 条检索题属于同一固定集，不重复计数。</p></div>
    <section className="metric-grid eval-metrics" aria-label="历史评测指标">
      <MetricCard label="有效 AI 分析" value={`${summary.system_result.model_mode_ai}/${summary.run_scope.total}`} suffix="条" icon="sparkle" tone="green" detail={`${summary.system_result.model_mode_unavailable} 条不可用 · 运行结果检查`} />
      <MetricCard label="核心答案符合参考" value={`${manual.answerable_core_answer_matches_reference}/${summary.run_scope.answerable}`} suffix="条" icon="check" tone="blue" detail="可回答题 · 历史人工核对" />
      <MetricCard label="无答案处理" value={`${manual.unanswerable_did_not_invent_requested_value_or_event}/${summary.run_scope.deliberately_unanswerable}`} suffix="条" icon="shield" tone="violet" detail="未编造所问数据 · 历史人工核对" />
      <MetricCard label="费用 / 延迟" value="—" suffix="" icon="clock" tone="amber" detail="历史未收录；最新数据见复测报告" />
    </section>
    <div className="report-navigation"><div className="report-tabs" role="tablist" aria-label="评测内容"><button type="button" role="tab" id="report-tab" aria-selected={tab === 'report'} aria-controls="report-panel" tabIndex={tab === 'report' ? 0 : -1} onKeyDown={handleTabKey} onClick={() => setTab('report')}><Icon name="chart" size={17} />评测报告</button><button type="button" role="tab" id="cases-tab" aria-selected={tab === 'cases'} aria-controls="cases-panel" tabIndex={tab === 'cases' ? 0 : -1} onKeyDown={handleTabKey} onClick={() => setTab('cases')}><Icon name="layers" size={17} />固定题集<span className="tab-count">{fixture.cases.length}</span></button></div><span className="report-scope">仓库快照 · 与当前所选项目数据独立</span></div>
    {tab === 'report' ? <div id="report-panel" role="tabpanel" aria-labelledby="report-tab">
      <div className="report-grid"><section className="panel retrieval-panel"><PanelHeader eyebrow="RETRIEVAL BENCHMARK" title="让正确的资料，排在前面" description={`${retrieval.scope.documents} 份项目资料 · ${retrieval.current.cases} 条可回答题 · 离线检索对比`} action={<span className="status-badge green">历史结果</span>} />
        <div className="benchmark-chart" role="img" aria-label={`Recall@1：原词元交集 ${percent(retrieval.baseline.recall_at_1)}，BM25 ${percent(retrieval.current.recall_at_1)}。`}><div className="benchmark-label"><span>Recall@1</span><span>正确资料排在首位的比例</span></div>{[{ label: '词元交集 v0', value: retrieval.baseline.recall_at_1, tone: 'baseline' }, { label: 'BM25 v1', value: retrieval.current.recall_at_1, tone: 'current' }].map((item) => <div className={`benchmark-row ${item.tone}`} key={item.label}><span>{item.label}</span><div className="bar-track"><span style={{ width: `${item.value * 100}%` }} /></div><strong>{percent(item.value)}</strong></div>)}</div>
        <div className="benchmark-table-wrap"><table className="benchmark-table"><caption className="sr-only">历史检索算法指标对比</caption><thead><tr><th scope="col">检索方法</th><th scope="col">Recall@1</th><th scope="col">Recall@3</th><th scope="col">MRR</th></tr></thead><tbody>{[{ label: '词元交集 v0', data: retrieval.baseline }, { label: 'BM25 v1', data: retrieval.current }].map((row) => <tr key={row.label}><th scope="row">{row.label}</th><td>{percent(row.data.recall_at_1)}</td><td>{percent(row.data.recall_at_3)}</td><td>{row.data.mrr.toFixed(4)}</td></tr>)}</tbody></table></div>
        <div className="benchmark-insight"><Icon name="check" size={16} /><span>首位排序从 <strong>29/30</strong> 到 <strong>30/30</strong>，修复了 1 条排序错误。</span></div>
      </section><section className="panel run-context"><PanelHeader eyebrow="RUN CONTEXT" title="这次记录，基于什么？" description="知道结果，也知道结果的边界。" /><dl><div><dt>评测日期</dt><dd>{summary.evaluated_at}</dd></div><div><dt>模型标识</dt><dd>{summary.model}</dd></div><div><dt>样本构成</dt><dd>30 条可回答 + 6 条故意无答案</dd></div><div><dt>评审方式</dt><dd>系统检查 + 人工核对</dd></div><div><dt>数据来源</dt><dd><code>examples/eval_summary_2026-09-16.json</code></dd></div></dl><div className="context-caveat"><Icon name="info" size={17} /><p>小型项目内题集，用于定位缺陷与回归。历史汇总没有逐题生成评分，也不能代表线上效果。</p></div></section></div>
      <section className="panel failure-taxonomy"><PanelHeader eyebrow="A CLEARER WAY TO DEBUG" title="失败要能被解释，也能被修复" description="下列为诊断视角；离线脚本已统计检索、证据/格式、未知问题安全和运行错误，语义质量仍需逐题复核。" action={<span className="status-badge muted">脚本已接入</span>} /><div className="taxonomy-grid">{[{ code: '01', title: '检索失败', icon: 'search', description: '正确资料未召回，或排在目标范围之外。' }, { code: '02', title: '回答质量', icon: 'sparkle', description: '核心答案错误、条件遗漏，或引用不支持结论。' }, { code: '03', title: '行为约束', icon: 'shield', description: '编造未知事实，或声称已执行未发生的操作。' }, { code: '04', title: '运行与协议', icon: 'pulse', description: '请求失败、输出结构异常，或校验未通过。' }].map((item) => <article key={item.code}><div><span className="taxonomy-icon"><Icon name={item.icon} size={19} /></span><span className="taxonomy-number">{item.code}</span></div><h3>{item.title}</h3><p>{item.description}</p></article>)}</div></section>
      <div className="next-run-strip"><span className="next-run-icon"><Icon name="flask" size={23} /></span><div><strong>最新真实复测，保留每道题的证据。</strong><p>36 条真实分析 · 35 条符合参考、1 条待确认 · 费用未知</p></div><a className="secondary-button" href={liveReportUrl} target="_blank" rel="noopener noreferrer">查看最新真实复测<Icon name="arrow" size={16} /></a></div>
    </div> : <section id="cases-panel" role="tabpanel" aria-labelledby="cases-tab" className="panel cases-panel"><PanelHeader eyebrow="FIXED DATASET" title="把评测标准，放到每一道题里" description="点击题目查看参考答案及历史检索排名。这里不生成新的模型调用。" /><div className="cases-controls"><div className="ticket-filters">{[{ key: 'all', label: `全部 ${fixture.cases.length}` }, { key: 'answerable', label: `可回答 ${summary.run_scope.answerable}` }, { key: 'unanswerable', label: `无答案 ${summary.run_scope.deliberately_unanswerable}` }].map((item) => <button type="button" key={item.key} aria-pressed={filter === item.key} className={filter === item.key ? 'active' : ''} onClick={() => setFilter(item.key)}>{item.label}</button>)}</div><label className="case-search"><Icon name="search" size={16} /><input aria-label="搜索评测题目" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索题目或编号…" /></label></div><div className="case-list" aria-label="固定评测题目">{visible.length === 0 ? <EmptyState icon="search" title="没有匹配的题目" description="更换关键词，或切换题目类型再试试。" /> : visible.map((item) => <button type="button" className="case-row" key={item.id} onClick={() => setSelected(item)}><span className="case-code">{item.id}</span><span className="case-question">{item.question}<small>{item.expected_document || '资料中故意不提供所问事实'}</small></span><span className={`status-badge ${item.expected_document ? 'green' : 'amber'}`}>{item.expected_document ? '可回答' : '无答案'}</span><Icon name="arrow" size={16} /></button>)}</div><div className="panel-footnote" role="status">当前展示 {visible.length} / {fixture.cases.length} 条 · 参考答案来自项目内可核对资料</div></section>}
    {selected && <Modal title={selected.id} description={selected.question} onClose={() => setSelected(null)}><div className="case-detail"><span className="result-label">参考答案 / 期望行为</span><p>{selected.reference_answer}</p><div className="case-evidence"><Icon name="book" size={17} /><span>{selected.expected_document || '应明确说明资料不足，不编造具体事实'}</span></div>{selectedRetrieval && <dl><div><dt>词元交集历史排名</dt><dd>#{selectedRetrieval.baseline_rank}</dd></div><div><dt>BM25 历史排名</dt><dd>#{selectedRetrieval.current_rank}</dd></div></dl>}<div className="snapshot-notice"><Icon name="info" size={17} /><p>历史汇总未收录逐题模型回答与人工评分，此处只展示参考答案及已有检索记录。</p></div><button type="button" className="secondary-button full" onClick={() => setSelected(null)}>返回题集</button></div></Modal>}
  </div>
}
