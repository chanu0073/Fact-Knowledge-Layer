import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { statusBadge, dataModeBadge } from '../utils'

const MODES = ['', 'sample', 'live-llm', 'fixture']

export default function Documents() {
  const [docs, setDocs] = useState([])
  const [status, setStatus] = useState('')
  const [mode, setMode] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    const params = {}
    if (status) params.status = status
    if (mode) params.data_mode = mode
    api.documents(params).then(setDocs).catch(() => setDocs([])).finally(() => setLoading(false))
  }, [status, mode])

  return (
    <div className="page">
      <h1>Documents</h1>
      <p className="muted mb">Pipeline state and provenance for every uploaded PDF. Each document records which mode produced its facts.</p>

      <div className="card mb flex">
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          {['UPLOADED', 'QUEUED', 'PARSING', 'PARSED', 'EXTRACTING', 'EXTRACTED', 'NORMALIZING', 'EMBEDDING', 'EMBEDDED', 'REASONING', 'REASONED', 'FAILED'].map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={mode} onChange={(e) => setMode(e.target.value)}>
          {MODES.map((m) => <option key={m} value={m}>{m === '' ? 'All data modes' : m}</option>)}
        </select>
      </div>

      <div className="card">
        {loading ? <p className="muted">Loading…</p> : docs.length === 0 ? (
          <p className="muted">No documents. Upload a PDF to begin.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Filename</th><th>Pages</th><th>Status</th><th>Data mode</th><th>Error</th><th>Uploaded</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><Link to={`/documents/${d.id}`}>{d.filename}</Link></td>
                  <td>{d.page_count ?? '—'}</td>
                  <td>{statusBadge(d.status)}</td>
                  <td>{dataModeBadge(d.data_mode)}</td>
                  <td className="muted">{d.error_message || '—'}</td>
                  <td className="muted">{new Date(d.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}