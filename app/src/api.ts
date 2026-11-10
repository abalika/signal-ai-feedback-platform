// Built assets run on the API origin; Vite development uses its local backend.
export const API_URL = (import.meta.env.VITE_API_URL ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')).replace(/\/$/, '')

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const controller = new AbortController()
  // Two model phases, each with one bounded retry, can take ~142 seconds.
  const timeout = window.setTimeout(() => controller.abort(), path.endsWith('/analyze') ? 155_000 : 15_000)
  const cancel = () => controller.abort()
  options?.signal?.addEventListener('abort', cancel, { once: true })
  if (options?.signal?.aborted) controller.abort()
  try {
    const headers = new Headers(options?.headers)
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json')
    const response = await fetch(`${API_URL}${path}`, {
      ...options,
      signal: controller.signal,
      headers,
    })
    const raw = await response.text()
    let payload: unknown
    try { payload = raw ? JSON.parse(raw) : null } catch { /* HTML gateway failures are never shown verbatim. */ }
    if (!response.ok) {
      const data = payload as { detail?: unknown; message?: unknown } | undefined
      const detail = data?.detail ?? data?.message
      const fields = Array.isArray(detail) ? detail.flatMap((item: unknown) => {
        if (!item || typeof item !== 'object' || !('msg' in item) || typeof item.msg !== 'string') return []
        const field = 'loc' in item && Array.isArray(item.loc) ? item.loc.slice(1).join('.') : ''
        return [`${field || '输入'}：${item.msg}`]
      }) : []
      const message = typeof detail === 'string' && detail.trim() ? detail : fields.join('；') || `请求失败（${response.status}），请稍后重试`
      throw new ApiError(response.status, message)
    }
    if (response.status === 204) return undefined as T
    if (payload == null) throw new ApiError(response.status, '服务返回了无效数据，请刷新后重试')
    return payload as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (controller.signal.aborted) throw new ApiError(0, '请求已取消或超时，请刷新核对结果后再重试')
    throw new ApiError(0, '无法连接本地服务，请确认服务已启动后重新连接')
  } finally {
    window.clearTimeout(timeout)
    options?.signal?.removeEventListener('abort', cancel)
  }
}
