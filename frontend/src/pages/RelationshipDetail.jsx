import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import api from '../api'
import { relBadge, fmtValue, groundingBadge } from '../utils'

function compareTerms(rel) {
  if (!rel) return []
  const a = rel.fact_a || {}
  const b = rel.fact_b || {}
  const checks = [
    ['Entity', compareStr(a.entity, b.entity)],
    ['Metric', compareStr(a.metric, b.metric)],
    ['Period', compareStr(a.period_raw, b.period_raw)],
    ['Scope', compareStr(a.scope, b.scope)],
    ['Observation type', compareStr(a.observation_type, b.observation_type)],
  ]
  return checks.map(([label, same]) => ({ label, same }))
}

function compareStr(x, y) {
  if (!x && !y) return true
  if (!x || !y) return false
  return String(x).trim().toLowerCase() === String(y).trim().toLowerCase()
}

function reasonsChecks(rel) {
  const list = Array.isArray(rel.reasons) ? rel.reasons : []
  return list.map((r) => (typeof r === 'string' ? r : r.reason || r.text))
}

function FactSide({ f, side }) {
  return (
    <div className="card">
      <div className="muted" style={{ textTransform: 'uppercase', fontSize: '0.75rem', letterSpacing: '0.04em' }}>
        Fact {side} {groundingBadge(f?.grounding)}
      </div>
      <h3 className="mt">{f?.entity || '—'} — {f?.metric || '—'}</h3>
      <div className="stat-value" style={{ fontSize: '1.3rem' }}>{fmtValue(f)}</div>
      <table className="table mt">
        <tbody>
          <tr><th style={{ width: 130 }}>Period</th><td>{f?.period_raw || '—'}</td></tr>
          <tr><th>Scope</th><td>{f?.scope || '—'}</td></tr>
          <tr><th>Type</th><td>{f?.observation_type || '—'}</td></tr>
          <tr><th>Confidence</th><td>{f?.extraction_confidence != null ? Math.round(f.extraction_confidence * 100) + '%' : '—'}</td></tr>
        </tbody>
      </table>
      {f?.evidence && f.evidence.length > 0 && (
        <>
          <h4 className="mt">Source evidence</h4>
          {f.evidence.map((ev, i) => (
            <div key={i} className="evidence-block mt">
              <div className="muted" style={{ fontSize: '0.8rem' }}>{f.document_filename} · p.{ev.page_number} · block #{ev.block_index} · {ev.evidence_type}</div>
              <pre className="evidence-pre">{ev.content}</pre>
            </div>
          ))}
        </>
      )}
      {f && <p className="mt"><Link to={`/facts/${f.id}`}>View fact →</Link></p>}
    </div>
  )
}

export default function RelationshipDetail({ mode }) {
  const { id } = useParams()
  const [rel, setRel] = useState(null)
  const [list, setList] = useState([])

  useEffect(() => {
    if (mode === 'list') api.relationships().then(setList).catch(() => setList([]))
    else if (id) api.relationship(id).then(setRel).catch(() => setRel(null))
  }, [mode, id])

  if (mode === 'list') {
    return (
      <div className="page">
        <h1>Relationships</h1>
        <p className="muted mb">Cross-fact comparisons discovered by the reasoning engine.</p>
        <div className="card">
          {list.length === 0 ? <p className="muted">No relationships yet.</p> : (
            <table className="table">
              <thead><tr><th>Fact A</th><th>vs</th><th>Fact B</th><th>Relationship</th><th>Confidence</th><th /></tr></thead>
              <tbody>
                {list.map((r) => (
                  <tr key={r.id}>
                    <td><Link to={`/facts/${r.fact_a_id}`}>Fact A →</Link></td>
                    <td className="muted">vs</td>
                    <td><Link to={`/facts/${r.fact_b_id}`}>Fact B →</Link></td>
                    <td>{relBadge(r.relationship_type)}</td>
                    <td>{Math.round((r.confidence || 0) * 100)}%</td>
                    <td><Link to={`/relationships/${r.id}`}>Details</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    )
  }

  if (!rel) return <div className="page"><p className="muted">Loading…</p></div>

  return (
    <div className="page">
      <Link to="/relationships" className="muted">← Back to relationships</Link>
      <div className="trace mt">
        <span><Link to={`/facts/${rel.fact_a_id}`}>Fact A</Link></span>
        <span>→</span>
        <span><Link to={`/facts/${rel.fact_b_id}`}>Fact B</Link></span>
        <span>→</span>
        <span>Reasoning</span>
        <span>→</span>
        <span>{relBadge(rel.relationship_type)}</span>
      </div>
      <div className="mt spread">
        <h1>Relationship</h1>
        {relBadge(rel.relationship_type)}
      </div>
      <p className="muted">Confidence: {Math.round((rel.confidence || 0) * 100)}%</p>

      <div className="grid grid-2">
        <FactSide f={rel.fact_a} side="A" />
        <FactSide f={rel.fact_b} side="B" />
      </div>

      <div className="card mt2">
        <h3>WHY? — Comparison terms</h3>
        <table className="table">
          <tbody>
            {compareTerms(rel).map((c) => (
              <tr key={c.label}>
                <th style={{ width: 160 }}>{c.label}</th>
                <td style={{ color: c.same ? 'var(--green)' : 'var(--text)' }}>
                  {c.same ? '✓ Same' : '— Different'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <h3 className="mt">Reasons</h3>
        <ul>
          {reasonsChecks(rel).map((r, i) => <li key={i}>{r}</li>)}
        </ul>
        {rel.llm_reasoning && (
          <>
            <h3 className="mt">Semantic reasoning</h3>
            <p>{rel.llm_reasoning}</p>
          </>
        )}
      </div>
    </div>
  )
}