export function relBadge(type) {
  switch (type) {
    case 'CORROBORATES': return <span className="badge badge-green">CORROBORATES</span>
    case 'LIKELY_CONTRADICTION': return <span className="badge badge-red">LIKELY CONTRADICTION</span>
    case 'APPARENT_CONTRADICTION_RESOLVED': return <span className="badge badge-amber">RESOLVED BY CONTEXT</span>
    case 'UNCERTAIN': return <span className="badge badge-gray">UNCERTAIN</span>
    default: return <span className="badge badge-blue">{type || '—'}</span>
  }
}

export function statusBadge(status) {
  const map = {
    UPLOADED: 'gray', PARSING: 'blue', EXTRACTING: 'blue', NORMALIZING: 'blue',
    EMBEDDING: 'blue', RECONCILING: 'blue', COMPLETED: 'green', FAILED: 'red',
  }
  const tone = map[status] || 'gray'
  return <span className={`badge badge-${tone}`}>{status || '—'}</span>
}

export function fmtValue(fact) {
  if (fact.raw_value) return fact.raw_value
  return `${fact.numeric_value ?? ''} ${fact.unit ?? ''}`.trim()
}