import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { relBadge } from '../utils'

const kindMeta = {
  corroboration: { title: '1. Corroborated Fact', tone: 'green' },
  contradiction: { title: '2. Genuine / Likely Contradiction', tone: 'red' },
  resolved: { title: '3. Apparent Contradiction Resolved by Context', tone: 'amber' },
  failure: { title: '4. Known Extraction / Reasoning Failure', tone: 'gray' },
}

export default function Cases() {
  const [cases, setCases] = useState([])
  const [error, setError] = useState(null)

  useEffect(() => { api.cases().then(setCases).catch((e) => setError(e.message)) }, [])

  return (
    <div className="page">
      <h1>Assignment Cases</h1>
      <p className="muted mb">
        The four required demonstration cases surfaced from real evaluation records. Synthetic fixtures are explicitly labelled as such.
      </p>
      {error && <div className="card" style={{ color: 'var(--red)' }}>{error}</div>}

      {Object.entries(kindMeta).map(([kind, meta]) => {
        const items = cases.filter((c) => c.kind === kind)
        return (
          <section key={kind} className="card mb">
            <h2 style={{ color: `var(--${meta.tone === 'green' ? 'green' : meta.tone === 'red' ? 'red' : meta.tone === 'amber' ? 'amber' : 'gray'})` }}>
              {meta.title}
            </h2>
            {items.length === 0 ? (
              <p className="muted">No case recorded yet.</p>
            ) : items.map((c) => (
              <div key={c.id} className="case-item" style={{ borderTop: '1px solid var(--border)', padding: '0.75rem 0' }}>
                {c.source === 'SYNTHETIC_EVALUATION_FIXTURE' && (
                  <span className="badge badge-amber" style={{ marginRight: 8 }}>SYNTHETIC</span>
                )}
                <div className="flex">
                  <span>{c.description || c.title}</span>
                  {c.expected_relationship && relBadge(c.expected_relationship)}
                </div>
                <p className="muted" style={{ marginTop: '0.4rem' }}>{c.explanation || ''}</p>
                {c.relationship_id && <Link to={`/relationships/${c.relationship_id}`}>View relationship →</Link>}
                {c.fact_ids?.length > 0 && (
                  <div>{c.fact_ids.map((fid) => <Link key={fid} to={`/facts/${fid}`} style={{ marginRight: 8 }}>Fact →</Link>)}</div>
                )}
              </div>
            ))}
          </section>
        )
      })}
    </div>
  )
}