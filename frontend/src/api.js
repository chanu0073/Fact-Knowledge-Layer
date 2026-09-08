const API_BASE =
  import.meta.env.VITE_API_BASE ||
  (window.location.port === '5173' ? 'http://localhost:8000' : '')

async function request(path, options = {}) {
  const headers = { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`API ${res.status}: ${body || res.statusText}`)
  }
  const ct = res.headers.get('content-type') || ''
  return ct.includes('application/json') ? res.json() : res.text()
}

export const api = {
  health: () => request('/api/health'),
  uploadDocument: (file) => {
    const fd = new FormData()
    fd.append('files', file)
    return fetch(`${API_BASE}/api/documents/upload`, { method: 'POST', body: fd }).then(async (r) => {
      if (!r.ok) { const b = await r.text().catch(() => ''); throw new Error(`API ${r.status}: ${b}`) }
      return r.json()
    })
  },
  documents: (params = {}) => request(`/api/documents${params ? `?${new URLSearchParams(params)}` : ''}`),
  document: (id) => request(`/api/documents/${id}`),
  documentEvidence: (id, params = {}) => request(`/api/documents/${id}/evidence?${new URLSearchParams(params)}`),
  documentFacts: (id, params = {}) => request(`/api/documents/${id}/facts?${new URLSearchParams(params)}`),
  documentLogs: (id) => request(`/api/documents/${id}/logs`),
  runPipeline: (id) => request(`/api/documents/${id}/pipeline`, { method: 'POST' }),
  facts: (params = {}) => request(`/api/facts?${new URLSearchParams(params)}`),
  fact: (id) => request(`/api/facts/${id}`),
  relationships: (params = {}) => request(`/api/relationships?${new URLSearchParams(params)}`),
  relationship: (id) => request(`/api/relationships/${id}`),
  cases: () => request('/api/evaluation/cases'),
  evaluationResults: () => request('/api/evaluation/results'),
  runEvaluation: () => request('/api/evaluation/run', { method: 'POST' }),
  stats: () => request('/api/stats'),
}

export default api
