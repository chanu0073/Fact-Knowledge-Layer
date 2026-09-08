import { useEffect, useState, useCallback } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../api'
import { statusBadge, dataModeBadge, groundingBadge, fmtValue, PIPELINE_ACTIVE } from '../utils'

export default function DocumentDetail() {
  const { id } = useParams()
  const [doc, setDoc] = useState(null)
  const [evidence, setEvidence] = useState([])
  const [facts, setFacts] = useState([])
  const [logs, setLogs] = useState([])
  const [error, setError] = useState(null)

  const refresh = useCallback(() => {
    api.document(id).then(setDoc).catch((e) => setError(e.message))
    api.documentEvidence(id).then(setEvidence).catch(() => setEvidence([]))
    api.documentFacts(id).then(setFacts).catch(() => setFacts([]))
    api.documentLogs(id).then(setLogs).catch(() => setLogs([]))
  }, [id])

  useEffect(() => { refresh() }, [refresh])

  // Poll while a run is progressing — including the transient stage-terminal
  // states (PARSED/EXTRACTED/NORMALIZED/EMBEDDED) that appear mid-pipeline, so
  // polling never stops (and no false success appears) before REASONED/FAILED.
  useEffect(() => {
    if (!doc || !PIPELINE_ACTIVE.includes(doc.status)) return undefined
    const t = setInterval(refresh, 2000)
    return () => clearInterval(t)
  }, [doc, refresh])

  const run = async () => {
    setError(null)
    try {
      await api.runPipeline(id)
      refresh()
    } catch (e) {
      setError(e.message)
    }
  }

  if (!doc) return <div className="page"><p className="muted">Loading document…</p></div>

  return (
    <div className="page">
      <Link to="/documents" className="muted">← Back to documents</Link>
      <div className="mt spread">
        <h1>{doc.filename}</h1>
        {statusBadge(doc.status)}
        {dataModeBadge(doc.data_mode)}
        <span className="badge badge-blue">provider: {doc.provider || '—'}</span>
      </div>
      <div className="trace mt">
        <span>Document</span><span>→</span><span><Link to={`/facts?document_id=${doc.id}`}>Facts ({facts.length})</Link></span><span>→</span><span>Evidence blocks ({evidence.length})</span>
      </div>

      {!PIPELINE_ACTIVE.includes(doc.status) && doc.status !== 'FAILED' && (
        <button className="btn btn-primary mt" onClick={run}>Re-run full pipeline</button>
      )}
      {error && <div className="card mt" style={{ color: 'var(--red)' }}>{error}</div>}

      {doc.status === 'FAILED' && doc.error_message && (
        <div className="card mt" style={{ borderLeft: '3px solid var(--red)' }}>
          <strong>Failure state:</strong> <span>{doc.error_message}</span>
        </div>
      )}

      <div className="grid grid-2 mt2">
        <div className="card">
          <h3>Facts in this document</h3>
          {facts.length === 0 ? <p className="muted">No facts extracted yet.</p> : (
            <table className="table">
              <thead><tr><th>Entity / Metric</th><th>Value</th><th>Period</th><th>Grounding</th></tr></thead>
              <tbody>
                {facts.map((f) => (
                  <tr key={f.id}>
                    <td><Link to={`/facts/${f.id}`}>{f.entity} — {f.metric}</Link></td>
                    <td>{fmtValue(f)}</td>
                    <td>{f.period_raw || '—'}</td>
                    <td>{groundingBadge(f.grounding)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card">
          <h3>Processing logs</h3>
          {logs.length === 0 ? <p className="muted">No processing logs yet.</p> : (
            <ul style={{ margin: 0, paddingLeft: 18 }}>
              {logs.map((l) => (
                <li key={l.id} className="muted" style={{ fontSize: '0.85rem', marginBottom: 4 }}>
                  [{l.stage}] {l.message}
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      <div className="card mt2">
        <h3>Evidence (document → page → block)</h3>
        {evidence.length === 0 ? <p className="muted">No evidence blocks. Run the pipeline (ingest) first.</p> : (
          <table className="table">
            <thead><tr><th>Page</th><th>Block</th><th>Type</th><th>Content</th></tr></thead>
            <tbody>
              {evidence.map((ev) => (
                <tr key={ev.id}>
                  <td>p.{ev.page_number}</td>
                  <td className="muted">#{ev.block_index}</td>
                  <td>{ev.evidence_type}</td>
                  <td className="evidence-pre" style={{ whiteSpace: 'pre-wrap' }}>{ev.content}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}