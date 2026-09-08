import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { relBadge, outcomeBadge, dataModeBadge } from '../utils'

const kindMeta = {
  corroboration: { title: '1. Corroborated Fact', tone: 'green' },
  contradiction: { title: '2. Genuine / Likely Contradiction', tone: 'red' },
  resolved: { title: '3. Apparent Contradiction Resolved by Context', tone: 'amber' },
  failure: { title: '4. Known Extraction / Reasoning Failure', tone: 'gray' },
}

export default function Cases() {
  const [cases, setCases] = useState([])
  const [results, setResults] = useState([])
  const [mode, setMode] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [notice, setNotice] = useState(null)

  const load = async () => {
    try {
      const [cs, rs] = await Promise.all([api.cases(), api.evaluationResults()])
      setCases(cs)
      setResults(rs)
      setMode(rs?.[0]?.data_mode ?? '')
    } catch (e) {
      setError(e.message)
    }
  }
  useEffect(() => { load() }, [])

  const rerun = async () => {
    setBusy(true); setNotice(null); setError(null)
    try {
      const rs = await api.runEvaluation()
      setResults(rs)
      setNotice('Reasoner re-ran over all cases (sample mode).')
      setError(null)
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="page">
      <h1>Assignment Cases</h1>
      <p className="muted mb">
        The four required demonstration cases. Outcome labels are distinct from relationship verdicts:
        PENDING means unresolved, FAIL means a real mismatch with the expected verdict, UNCERTAIN is a valid verdict — none are shown as PASS.
      </p>
      {mode && <p className="mb" style={{ fontSize: '0.9em' }}>Evaluation data mode: {dataModeBadge(mode)}</p>}
      {error && <div className="card" style={{ color: 'var(--red)' }}>{error}</div>}
      {notice && <div className="card" style={{ color: 'var(--green)' }}>{notice}</div>}

      <div className="card mb flex">
        <button className="btn" disabled={busy} onClick={rerun}>
          {busy ? 'Running…' : 'Re-run evaluation (sample)'}
        </button>
      </div>

      {Object.entries(kindMeta).map(([kind, meta]) => {
        const rs = results.filter((r) => r.kind === kind)
        const cs = cases.filter((c) => c.kind === kind)
        return (
          <section key={kind} className="card mb">
            <h2 style={{ color: `var(--${meta.tone === 'green' ? 'green' : meta.tone === 'red' ? 'red' : meta.tone === 'amber' ? 'amber' : 'gray'})` }}>
              {meta.title}
            </h2>
            {rs.length === 0 ? (
              <p className="muted">No evaluation records yet (register the cases first).</p>
            ) : rs.map((r) => {
              const row = cs.find((c) => c.relationship_id && c.relationship_id === r.relationship_id) || cs[0]
              return (
                <div key={r.case_key} className="case-item" style={{ borderTop: '1px solid var(--border)', padding: '0.75rem 0' }}>
                  <div className="flex">
                    {outcomeBadge(r.outcome)}
                    {r.source === 'SYNTHETIC_EVALUATION_FIXTURE' && (
                      <span className="badge badge-blue" style={{ marginLeft: 8 }}>SYNTHETIC FIXTURE</span>
                    )}
                    <span style={{ marginLeft: 8 }}>{r.title}</span>
                  </div>
                  <p className="muted" style={{ marginTop: '0.4rem', fontSize: '0.9em' }}>
                    Expected: {relBadge(r.expected)}
                    {r.actual ? <span>&nbsp;→ Actual: {relBadge(r.actual)}</span> : <span>&nbsp;— no verdict yet</span>}
                    {r.confidence ? ` · confidence ${Math.round(r.confidence * 100)}%` : ''}
                  </p>
                  {r.outcome === 'FAIL' && (
                    <p className="muted" style={{ color: 'var(--red)', marginTop: '0.3rem', fontSize: '0.85em' }}>
                      {r.note} — actual {r.actual ?? 'none'} differs from expected {r.expected}. Reasons are visible on the relationship page.
                    </p>
                  )}
                  {r.outcome === 'PENDING' && (
                    <p className="muted" style={{ color: 'var(--amber)', marginTop: '0.3rem', fontSize: '0.85em' }}>
                      {r.note || 'Not yet resolvable against the current corpus.'}
                    </p>
                  )}
                  {r.actual && r.reasons?.length > 0 && (
                    <ul className="muted" style={{ margin: '0.4rem 0 0', paddingLeft: 18, fontSize: '0.85em' }}>
                      {r.reasons.slice(0, 4).map((rea, i) => <li key={i}>{typeof rea === 'string' ? rea : rea?.reason || rea?.text}</li>)}
                    </ul>
                  )}
                  <div style={{ marginTop: '0.5rem' }}>
                    {r.relationship_id && <Link to={`/relationships/${r.relationship_id}`} style={{ marginRight: 12 }}>View relationship →</Link>}
                    {row?.fact_ids?.map((fid) => <Link key={fid} to={`/facts/${fid}`} style={{ marginRight: 8 }}>Fact →</Link>)}
                  </div>
                </div>
              )
            })}
          </section>
        )
      })}
    </div>
  )
}