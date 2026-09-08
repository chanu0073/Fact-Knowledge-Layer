import { useState, useRef } from 'react'
import { Link } from 'react-router-dom'
import api from '../api'
import { statusBadge, dataModeBadge } from '../utils'

export default function Upload() {
  const [files, setFiles] = useState([])
  const [uploading, setUploading] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const inputRef = useRef(null)

  const onPick = (list) => {
    const accepted = Array.from(list).filter((f) => f.type === 'application/pdf' || f.name.endsWith('.pdf'))
    setFiles(accepted)
  }

  const upload = async () => {
    if (!files.length) return
    setUploading(true); setError(null); setResult(null)
    try {
      const jobs = []
      for (const f of files) jobs.push(api.uploadDocument(f))
      const res = await Promise.all(jobs)
      setResult(res)
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="page">
      <h1>Upload Documents</h1>
      <p className="muted mb">Upload one or more PDFs. Processing runs page-by-page; every extracted fact is grounded to source evidence (page + block).</p>

      <div className="card">
        <div
          className="drop"
          style={{ border: '2px dashed var(--border)', borderRadius: 8, padding: '2.5rem', textAlign: 'center' }}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => { e.preventDefault(); onPick(e.dataTransfer.files) }}
        >
          <p>Drag &amp; drop PDFs here, or</p>
          <button className="btn btn-primary" onClick={() => inputRef.current?.click()}>Choose files</button>
          <input ref={inputRef} type="file" accept="application/pdf" multiple hidden onChange={(e) => onPick(e.target.files)} />
        </div>

        {files.length > 0 && (
          <div className="mt">
            <h3>Selected files</h3>
            <ul>
              {files.map((f, i) => <li key={i}>{f.name} ({Math.round(f.size / 1024)} KB)</li>)}
            </ul>
            <button className="btn btn-primary" disabled={uploading} onClick={upload}>
              {uploading ? 'Uploading…' : 'Upload & Process'}
            </button>
          </div>
        )}

        {error && <div className="mt" style={{ color: 'var(--red)' }}>Upload failed: {error}</div>}
        {result && (
          <div className="mt">
            <h3>Uploaded</h3>
            {result.map((r) => r.documents?.map((d) => (
              <div key={d.id} className="flex">
                <span>{d.filename}</span>
                <span>{dataModeBadge(d.data_mode)}</span>
                <span>{statusBadge(d.status)}</span>
                <Link to={`/documents/${d.id}`} style={{ marginLeft: 8 }}>Open →</Link>
              </div>
            )))}
            <p className="muted">Run the full pipeline from the document page, or via the script.</p>
          </div>
        )}
      </div>
    </div>
  )
}