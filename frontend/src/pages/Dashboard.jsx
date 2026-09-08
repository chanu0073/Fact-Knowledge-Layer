import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { statusBadge, dataModeBadge } from '../utils'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [docs, setDocs] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message))
    api.documents().then(setDocs).catch(() => {})
  }, [])

  const cards = [
    { label: 'Documents', value: stats?.documents ?? docs.length, route: '/documents' },
    { label: 'Facts', value: stats?.facts ?? 0, route: '/facts' },
    { label: 'Corroborations', value: stats?.relationships?.CORROBORATES ?? 0, route: '/relationships' },
    { label: 'Likely Contradictions', value: stats?.relationships?.LIKELY_CONTRADICTION ?? 0, route: '/relationships' },
    { label: 'Resolved Contradictions', value: stats?.relationships?.APPARENT_CONTRADICTION_RESOLVED ?? 0, route: '/relationships' },
    { label: 'Uncertain', value: stats?.relationships?.UNCERTAIN ?? 0, route: '/relationships' },
  ]

  const modes = stats?.documents_by_mode ?? {}
  const allSample = !Object.keys(modes).some((m) => m !== 'sample')

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="muted mb">Knowledge layer overview. Relationship counts reflect pairwise comparisons between extracted facts.</p>
      {stats && (
        <div className="card mb">
          <p style={{ fontSize: '0.9em', margin: 0 }}>
            <strong>Data mode:</strong>&nbsp;
            {stats.data_mode === 'sample'
              ? <span className="badge badge-gray">SAMPLE / HEURISTIC</span>
              : <span className="badge badge-amber">LIVE LLM</span>}
            &nbsp;|&nbsp; LLM provider: {stats.provider ?? '—'} &nbsp;|&nbsp; Embedding provider: {stats.embedding_provider ?? '—'}
          </p>
          {Object.keys(modes).length > 0 && (
            <p style={{ fontSize: '0.85em', margin: '0.4rem 0 0' }} className="muted">
              Documents by mode: {Object.entries(modes).map(([m, n]) => (
                <span key={m} style={{ marginRight: 10 }}>{dataModeBadge(m)} × {n}</span>
              ))}
              {allSample && Object.keys(modes).length > 0 && ' — current corpus is entirely sample/heuristic'}
            </p>
          )}
        </div>
      )}
      {error && <div className="card" style={{ color: 'var(--red)' }}>Error: {error}</div>}
      <div className="grid grid-4 mb">
        {cards.map((c) => (
          <Link key={c.label} to={c.route} style={{ color: 'inherit', textDecoration: 'none' }}>
            <div className="card">
              <div className="stat-label">{c.label}</div>
              <div className="stat-value">{c.value}</div>
            </div>
          </Link>
        ))}
      </div>
      <h2 className="mt">Documents</h2>
      <div className="card">
        {docs.length === 0 ? (
          <p className="muted">No documents yet. Upload a PDF to begin.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Filename</th><th>Pages</th><th>Status</th><th>Data mode</th><th>Uploaded</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td><Link to={`/documents/${d.id}`}>{d.filename}</Link></td>
                  <td>{d.page_count ?? '—'}</td>
                  <td>{statusBadge(d.status)}</td>
                  <td>{dataModeBadge(d.data_mode)}</td>
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