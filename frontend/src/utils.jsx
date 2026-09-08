export function relBadge(type) {
  switch (type) {
    case 'CORROBORATES': return <span className="badge badge-green">CORROBORATES</span>
    case 'LIKELY_CONTRADICTION': return <span className="badge badge-red">LIKELY CONTRADICTION</span>
    case 'APPARENT_CONTRADICTION_RESOLVED': return <span className="badge badge-amber">RESOLVED BY CONTEXT</span>
    case 'UNCERTAIN': return <span className="badge badge-gray">UNCERTAIN</span>
    default: return <span className="badge badge-blue">{type || '—'}</span>
  }
}

// Document lifecycle statuses actually produced by the pipeline. Each runs
// state is visually distinct from terminal states; FAILED is always red.
const statusMap = {
  UPLOADED: 'gray', QUEUED: 'gray', PROCESSING: 'blue', PARSING: 'blue',
  PARSED: 'blue', EXTRACTING: 'blue', EXTRACTED: 'blue', NORMALIZING: 'blue',
  EMBEDDING: 'blue', EMBEDDED: 'blue', REASONING: 'blue', REASONED: 'green',
  NORMALIZED: 'green', FAILED: 'red',
}
export function statusBadge(status) {
  const tone = statusMap[status] || 'gray'
  return <span className={`badge badge-${tone}`}>{status || '—'}</span>
}

// Data provenance: what produced a document's facts. Distinct from status and
// from verdicts — never conflated.
export function dataModeBadge(mode) {
  const label = mode === 'live-llm' ? 'LIVE LLM' : mode === 'fixture' ? 'FIXTURE' : 'SAMPLE'
  const tone = mode === 'live-llm' ? 'amber' : mode === 'fixture' ? 'blue' : 'gray'
  return <span className={`badge badge-${tone}`}>{label}</span>
}

// Evaluation-case outcomes. PENDING/FAIL are NEVER shown as PASS.
export function outcomeBadge(outcome) {
  switch (outcome) {
    case 'PASS': return <span className="badge badge-green">PASS</span>
    case 'FAIL': return <span className="badge badge-red">FAIL</span>
    case 'PENDING': return <span className="badge badge-amber">PENDING</span>
    default: return <span className="badge badge-gray">{outcome || 'NOT REGISTERED'}</span>
  }
}

export function groundingBadge(g) {
  if (!g) return null
  return <span className={`badge ${g === 'block' ? 'badge-green' : 'badge-amber'}`}>{g === 'block' ? 'BLOCK-GROUNDED' : 'PAGE-GROUNDED'}</span>
}

export function fmtValue(fact) {
  if (fact.raw_value) return fact.raw_value
  return `${fact.numeric_value ?? ''} ${fact.unit ?? ''}`.trim()
}