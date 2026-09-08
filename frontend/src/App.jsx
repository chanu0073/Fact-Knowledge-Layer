import { Routes, Route, NavLink, Navigate } from 'react-router-dom'
import Dashboard from './pages/Dashboard.jsx'
import Upload from './pages/Upload.jsx'
import Documents from './pages/Documents.jsx'
import DocumentDetail from './pages/DocumentDetail.jsx'
import FactExplorer from './pages/FactExplorer.jsx'
import FactDetail from './pages/FactDetail.jsx'
import RelationshipDetail from './pages/RelationshipDetail.jsx'
import Cases from './pages/Cases.jsx'
import './styles/app.css'

export default function App() {
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">F</span>
          <span className="brand-name">Fact Knowledge Layer</span>
        </div>
        <nav className="nav">
          <NavLink to="/" end>Dashboard</NavLink>
          <NavLink to="/upload">Upload</NavLink>
          <NavLink to="/documents">Documents</NavLink>
          <NavLink to="/facts">Facts</NavLink>
          <NavLink to="/relationships">Relationships</NavLink>
          <NavLink to="/cases">Assignment Cases</NavLink>
        </nav>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/upload" element={<Upload />} />
          <Route path="/documents" element={<Documents />} />
          <Route path="/documents/:id" element={<DocumentDetail />} />
          <Route path="/facts" element={<FactExplorer />} />
          <Route path="/facts/:id" element={<FactDetail />} />
          <Route path="/relationships" element={<RelationshipDetail mode="list" />} />
          <Route path="/relationships/:id" element={<RelationshipDetail mode="detail" />} />
          <Route path="/cases" element={<Cases />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </div>
  )
}
