// Typed client for the Remastr REST API (mirrors backend/src/remastr/models.py).

export type Library = { key: string; title: string; type: string }

export type PlexItem = {
  rating_key: string
  title: string
  type: string
  library: string
  show: string | null
  season: number | null
  episode: number | null
  year: number | null
  file: string
  size: number | null
  width: number | null
  height: number | null
  duration_s: number | null
  container: string | null
  video_codec: string | null
}

export type Preset = { id: string; name: string; description: string; preview_only: boolean }

export type PreviewClip = { preset: string; file: string }
export type PreviewRun = { id: string; start_s: number; duration_s: number; created_at: string; clips: PreviewClip[] }
export type OutputInfo = {
  file: string
  size: number
  preset: string | null
  preset_name: string | null
  codec: string | null
  quality: number | null
  description: string | null
  created_at: string | null
}
export type LocalState = { source: string | null; previews: PreviewRun[]; outputs: OutputInfo[] }
export type ItemDetail = { item: PlexItem; local: LocalState }

export type JobType = 'download' | 'preview' | 'process' | 'upload'
export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
export type Job = {
  id: number
  type: JobType
  status: JobStatus
  rating_key: string
  title: string
  params: Record<string, unknown>
  depends_on: number | null
  progress: number
  message: string
  result: Record<string, unknown>
  created_at: string
  updated_at: string
}

export type Codec = 'hevc' | 'av1'
export type UploadMode = 'version' | 'replace'
export type ProcessRequest = { preset: string; codec: Codec; quality: number }

/** Keep in sync with DEFAULT_QUALITY in backend/src/remastr/models.py. The default preset is the first one listed. */
export const DEFAULT_QUALITY = 26
export type UploadRequest = { mode: UploadMode; confirm: boolean }

const TOKEN_KEY = 'remastr.token'

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? ''
  } catch {
    return ''
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token)
  } catch {
    // storage unavailable: token only lives for this page view
  }
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {}
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  const res = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      // keep statusText
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

const enc = encodeURIComponent

export const api = {
  libraries: () => request<Library[]>('GET', '/api/libraries'),
  search: (q: string, library?: string) =>
    request<PlexItem[]>('GET', `/api/search?q=${enc(q)}${library ? `&library=${enc(library)}` : ''}`),
  presets: () => request<Preset[]>('GET', '/api/presets'),
  item: (rk: string) => request<ItemDetail>('GET', `/api/items/${rk}`),
  download: (rk: string) => request<Job>('POST', `/api/items/${rk}/download`),
  preview: (rk: string, presets: string[], start_s: number, duration_s: number) =>
    request<Job>('POST', `/api/items/${rk}/previews`, { presets, start_s, duration_s }),
  process: (rk: string, body: ProcessRequest) => request<Job>('POST', `/api/items/${rk}/process`, body),
  upload: (rk: string, body: UploadRequest) => request<Job>('POST', `/api/items/${rk}/upload`, body),
  batch: (rating_keys: string[], process: ProcessRequest, upload: UploadRequest | null) =>
    request<Job[]>('POST', '/api/batch', { rating_keys, process, upload }),
  jobs: (params: { rating_key?: string; active_only?: boolean } = {}) => {
    const q = new URLSearchParams()
    if (params.rating_key) q.set('rating_key', params.rating_key)
    if (params.active_only) q.set('active_only', 'true')
    return request<Job[]>('GET', `/api/jobs?${q}`)
  },
  cancel: (id: number) => request<Job>('POST', `/api/jobs/${id}/cancel`),
}

/** URL for <video src>: the token goes into the query because media elements cannot send headers. */
export function fileUrl(rk: string, path: string): string {
  const token = getToken()
  const url = `/api/items/${rk}/files/${path.split('/').map(enc).join('/')}`
  return token ? `${url}?token=${enc(token)}` : url
}

export function itemLabel(item: PlexItem): string {
  if (item.show && item.season != null && item.episode != null) {
    const s = String(item.season).padStart(2, '0')
    const e = String(item.episode).padStart(2, '0')
    return `${item.show} · S${s}E${e} · ${item.title}`
  }
  return item.year ? `${item.title} (${item.year})` : item.title
}

export function formatBytes(n: number | null | undefined): string {
  if (!n) return '–'
  return n > 1e9 ? `${(n / 1e9).toFixed(1)} GB` : `${(n / 1e6).toFixed(0)} MB`
}

export function formatDuration(s: number | null | undefined): string {
  if (!s) return '–'
  const m = Math.floor(s / 60)
  return m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`
}
