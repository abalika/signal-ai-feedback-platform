import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'

export function Icon({ name, size = 18 }: { name: string; size?: number }) {
  const paths: Record<string, ReactNode> = {
    settings: <><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" /><circle cx="15" cy="17" r="3" /></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1.5" /><rect x="14" y="3" width="7" height="7" rx="1.5" /><rect x="3" y="14" width="7" height="7" rx="1.5" /><rect x="14" y="14" width="7" height="7" rx="1.5" /></>,
    flask: <><path d="M9 3h6M10 3v6L4.5 18a2 2 0 0 0 1.7 3h11.6a2 2 0 0 0 1.7-3L14 9V3M8 13h8" /><path d="M10 17h.01M14 18h.01" /></>,
    shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z" /><path d="m8 12 3 3 5-6" /></>,
    chart: <><path d="M4 3v17h17M8 15v-4M13 15V7M18 15V5" /></>,
    download: <><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5" /></>,
    folder: <path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11H3z" />,
    layers: <><path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7h.01" /></>,
    plus: <><path d="M12 5v14M5 12h14" /></>,
    arrow: <><path d="M5 12h14" /><path d="m13 6 6 6-6 6" /></>,
    chevron: <path d="m8 10 4 4 4-4" />,
    search: <><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></>,
    book: <><path d="M5 4.5A2.5 2.5 0 0 1 7.5 2H19v18H7.5A2.5 2.5 0 0 1 5 17.5z" /><path d="M5 17.5A2.5 2.5 0 0 1 7.5 15H19" /></>,
    inbox: <><path d="M4 5h16v14H4z" /><path d="M4 14h4l1.5 2h5L16 14h4" /></>,
    ticket: <><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5V9a2 2 0 0 0 0 6v2.5a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 17.5V15a2 2 0 0 0 0-6z" /><path d="M9 8v1M9 11.5v1M9 15v1" /></>,
    pulse: <><path d="M3 12h4l2-6 4 12 2-6h6" /></>,
    sparkle: <><path d="m12 3 1.2 4.8L18 9l-4.8 1.2L12 15l-1.2-4.8L6 9l4.8-1.2z" /><path d="m19 15 .6 2.4L22 18l-2.4.6L19 21l-.6-2.4L16 18l2.4-.6z" /></>,
    check: <path d="m5 12 4 4L19 6" />,
    alert: <><path d="M12 3 2.7 20h18.6z" /><path d="M12 9v5M12 17.5v.5" /></>,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    external: <><path d="M14 5h5v5M19 5l-8 8" /><path d="M18 13v5H5V5h5" /></>,
    close: <><path d="m6 6 12 12M18 6 6 18" /></>,
    refresh: <><path d="M20 11a8 8 0 0 0-14.7-4L3 10" /><path d="M3 5v5h5" /><path d="M4 13a8 8 0 0 0 14.7 4L21 14" /><path d="M21 19v-5h-5" /></>,
    user: <><circle cx="12" cy="8" r="3" /><path d="M5 20a7 7 0 0 1 14 0" /></>,
    menu: <><path d="M4 6h16M4 12h16M4 18h16" /></>,
  }
  return <svg className="icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export function EmptyState({ icon, title, description, action }: { icon: string; title: string; description: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon name={icon} size={22} /></div><strong>{title}</strong><p>{description}</p>{action}</div>
}

export function MetricCard({ label, value, suffix, icon, tone, detail }: { label: string; value: number | string; suffix: string; icon: string; tone: string; detail: string }) {
  return <article className="metric-card"><div className="metric-top"><span className="metric-label">{label}</span><div className={`metric-icon ${tone}`}><Icon name={icon} size={18} /></div></div><div className="metric-value">{value}<small>{suffix}</small></div><p>{detail}</p></article>
}

export function PanelHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return <header className="panel-header"><div><span className="panel-eyebrow">{eyebrow}</span><h2>{title}</h2><p>{description}</p></div>{action}</header>
}

export function Modal({ title, description, onClose, children }: { title: string; description: string; onClose: () => void; children: ReactNode }) {
  const dialog = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const element = dialog.current
    element?.showModal()
    return () => { element?.close(); previous?.focus() }
  }, [])
  return <dialog ref={dialog} className="modal" aria-label={title} onCancel={(event) => { event.preventDefault(); onClose() }} onClick={(event) => { if (event.target === event.currentTarget) { const rect = event.currentTarget.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) onClose() } }}><button type="button" className="modal-close icon-button" onClick={onClose} aria-label="关闭"><Icon name="close" size={18} /></button><div className="modal-kicker">SIGNAL / WORKSPACE</div><h2>{title}</h2><p>{description}</p>{children}</dialog>
}
