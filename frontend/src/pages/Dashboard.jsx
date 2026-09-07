import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'

export default function Dashboard() {
  const [stats, setStats] = useState(null)
  const [docs, setDocs] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message))
    api.documents().then(setDocs).catch(() => {})
  }, [])

  const cards = [
    { label: 'Documents', value: stats?.documents ?? docs.length, route: '/upload' },
    { label: 'Facts', value: stats?.facts ?? 0, route: '/facts' },
    { label: 'Corroborations', value: stats?.relationships?.CORROBORATES ?? 0, route: '/relationships' },
    { label: 'Likely Contradictions', value: stats?.relationships?.LIKELY_CONTRADICTION ?? 0, route: '/relationships' },
    { label: 'Resolved Contradictions', value: stats?.relationships?.APPARENT_CONTRADICTION_RESOLVED ?? 0, route: '/relationships' },
    { label: 'Uncertain', value: stats?.relationships?.UNCERTAIN ?? 0, route: '/relationships' },
  ]

  return (
    <div className="page">
      <h1>Dashboard</h1>
      <p className="muted mb">Knowledge layer overview. Relationship counts reflect pairwise comparisons between extracted facts.</p>
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
              <tr><th>Filename</th><th>Pages</th><th>Status</th><th>Uploaded</th></tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.id}>
                  <td>{d.filename}</td>
                  <td>{d.page_count ?? '—'}</td>
                  <td>{d.status ?? '—'}</td>
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