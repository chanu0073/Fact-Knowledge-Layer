import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import api from '../api'
import { fmtValue, groundingBadge } from '../utils'

export default function FactExplorer() {
  const [params] = useSearchParams()
  const [facts, setFacts] = useState([])
  const [docs, setDocs] = useState([])
  const [q, setQ] = useState('')
  const [docId, setDocId] = useState(params.get('document_id') || '')
  const [type, setType] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => { api.documents().then(setDocs).catch(() => {}) }, [])

  useEffect(() => {
    setLoading(true)
    const p = {}
    if (q) p.q = q
    if (docId) p.document_id = docId
    if (type) p.observation_type = type
    api.facts(p).then(setFacts).catch(() => setFacts([])).finally(() => setLoading(false))
  }, [q, docId, type])

  return (
    <div className="page">
      <h1>Fact Explorer</h1>
      <p className="muted mb">Facts extracted from uploaded documents. Each fact is linked to its source evidence.</p>

      <div className="card mb flex">
        <input className="filter-input" placeholder="Search facts…" value={q} onChange={(e) => setQ(e.target.value)} />
        <select value={docId} onChange={(e) => setDocId(e.target.value)}>
          <option value="">All documents</option>
          {docs.map((d) => <option key={d.id} value={d.id}>{d.filename}</option>)}
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All observation types</option>
          {['actual', 'estimate', 'forecast', 'projection', 'guidance', 'historical', 'unknown'].map((t) => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      <div className="card">
        {loading ? <p className="muted">Loading…</p> : facts.length === 0 ? (
          <p className="muted">No facts found.</p>
        ) : (
          <table className="table">
            <thead>
              <tr><th>Entity</th><th>Metric</th><th>Value</th><th>Period</th><th>Scope</th><th>Type</th><th>Conf.</th><th>Source</th><th>Grounding</th></tr>
            </thead>
            <tbody>
              {facts.map((f) => (
                <tr key={f.id}>
                  <td><Link to={`/facts/${f.id}`}>{f.entity}</Link></td>
                  <td>{f.metric}</td>
                  <td>{fmtValue(f)}</td>
                  <td>{f.period_raw || '—'}</td>
                  <td>{f.scope || '—'}</td>
                  <td>{f.observation_type || '—'}</td>
                  <td>{f.extraction_confidence != null ? Math.round(f.extraction_confidence * 100) + '%' : '—'}</td>
                  <td className="muted">{f.document_filename ? `${f.document_filename} p.${f.page_number ?? '?'}` : '—'}</td>
                  <td>{groundingBadge(f.grounding)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}