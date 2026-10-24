import type { NavKey } from './types'

export const navItems: Array<{ key: NavKey; label: string; icon: string }> = [
  { key: 'overview', label: '工作台总览', icon: 'grid' },
  { key: 'feedback', label: '反馈收件箱', icon: 'inbox' },
  { key: 'tickets', label: '技术工单', icon: 'ticket' },
  { key: 'documents', label: '产品资料库', icon: 'book' },
  { key: 'evaluations', label: '评测中心', icon: 'flask' },
]

const statusLabels: Record<string, { label: string; tone: string }> = {
  new: { label: '待分析', tone: 'amber' },
  pending: { label: '待分析', tone: 'amber' },
  analyzed: { label: '待复核', tone: 'blue' },
  in_review: { label: '待复核', tone: 'blue' },
  ticket_created: { label: '已建工单', tone: 'green' },
  ticketed: { label: '已建工单', tone: 'green' },
  resolved: { label: '已解决', tone: 'green' },
}

export function formatDate(value: string) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(date)
}

export function statusMeta(value: string) {
  return statusLabels[value] ?? { label: value || '未标记', tone: 'muted' }
}

export function shortText(value: string, length = 112) {
  const cleaned = value.replace(/\s+/g, ' ').trim()
  return cleaned.length > length ? `${cleaned.slice(0, length)}…` : cleaned
}
