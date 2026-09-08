import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../api'
import { relBadge, fmtValue, groundingBadge } from '../utils'

export default function FactDetail() {
  const { id } = useParams()
  const [fact, setFact] = useState(null)

  useEffect(() => { api.fact(id).then(setFact).catch(() => setFact(null)) }, [id])

  if (!fact) return <div className="page"><p className="muted">Loading fact…</p></div>

  const rows = [
    ['Entity', fact.entity],
    ['Metric', fact.metric],
    ['Definition', fact.definition],
    ['Value (as reported)', fmtValue(fact)],
    ['Period', fact.period_raw || '—'],
    ['Observation type', fact.observation_type || '—'],
    ['Scope', fact.scope || '—'],
    ['Geography', fact.geography || '—'],
    ['Confidence', fact.extraction_confidence != null ? Math.round(fact.extraction_confidence * 100) + '%' : '—'],
  ]
  const qualifiers = fact.qualifiers && Object.keys(fact.qualifiers).length ? fact.qualifiers : null

  return (
    <div className="page">
      <Link to="/facts" className="muted">← Back to facts</Link>
      <div className="trace mt">
        <span><Link to={`/documents/${fact.document_id}`}>{fact.document_filename || 'Document'}</Link></span>
        <span>→</span>
        <span>Evidence blocks ({fact.evidence?.length ?? 0})</span>
        <span>→</span>
        <span>Fact</span>
        <span>→</span>
        <span>Verdicts ({fact.relationships?.length ?? 0})</span>
      </div>
      <h1 className="mt">Fact {groundingBadge(fact.grounding)}</h1>
      <div className="grid grid-2">
        <div className="card">
          <h3>{fact.entity} — {fact.metric}</h3>
          <table className="table">
            <tbody>
              {rows.map(([k, v]) => (
                <tr key={k}><th style={{ width: 160 }}>{k}</th><td>{v || '—'}</td></tr>
              ))}
              {qualifiers && (
                <tr><th>Qualifiers</th><td><pre className="evidence-pre">{JSON.stringify(qualifiers, null, 2)}</pre></td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="card">
          <h3>Source Evidence</h3>
          {!fact.evidence?.length ? <p className="muted">No evidence recorded.</p> : fact.evidence.map((ev) => (
            <div key={ev.id} className="evidence-block">
              <div className="muted" style={{ fontSize: '0.8rem' }}>
                {fact.document_filename} · p.{ev.page_number} · block #{ev.block_index} · {ev.evidence_type}
              </div>
              <pre className="evidence-pre">{ev.content}</pre>
            </div>
          ))}
        </div>
      </div>

      <div className="card mt2">
        <h3>Relationships</h3>
        {!fact.relationships?.length ? <p className="muted">No relationships discovered yet.</p> : (
          <table className="table">
            <thead><tr><th>Related fact</th><th>Relationship</th><th>Confidence</th><th /></tr></thead>
            <tbody>
              {fact.relationships.map((r) => {
                const other = r.fact_a_id === fact.id ? r.fact_b : r.fact_a
                return (
                  <tr key={r.id}>
                    <td>{other ? `${other.entity} — ${other.metric} (${other.period_raw || 'no period'})` : ''}</td>
                    <td>{relBadge(r.relationship_type)}</td>
                    <td>{Math.round(r.confidence * 100)}%</td>
                    <td><Link to={`/relationships/${r.id}`}>Details</Link></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}