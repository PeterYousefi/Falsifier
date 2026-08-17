/**
 * src/App.tsx
 * Root application shell: top nav, screen router, page footer with locked non-claim.
 * All screens render with fixture data by default (VITE_DATA_SOURCE=fixture).
 */
import React, { useEffect } from 'react'
import { useStore } from './store'
import SystemScreen from './screens/SystemScreen'
import CandidateDetail from './screens/CandidateDetail'
import ChatPanel from './screens/ChatPanel'
import UploadFlow from './screens/UploadFlow'
import TrainingSandbox from './screens/TrainingSandbox'
import ProvenancePage from './screens/ProvenancePage'
import LiveConsole from './screens/LiveConsole'

const SCREENS = [
  { id: 'system',     label: 'System',    title: 'Orbital system browse' },
  { id: 'detail',     label: 'Candidate', title: 'Candidate detail' },
  { id: 'chat',       label: 'Chat',      title: 'Pipeline chat' },
  { id: 'upload',     label: 'Upload',    title: 'Light curve upload' },
  { id: 'training',   label: 'Training',  title: 'Training sandbox' },
  { id: 'provenance', label: 'Provenance', title: 'Data provenance' },
  { id: 'console',    label: 'Console',   title: 'Live console' },
]

const LOCKED_NON_CLAIM =
  'Not a biosignature detector · No exoplanet biosignature has ever been confirmed · ' +
  'Classifier probability is a ranking score only — not a verdict'

export default function App() {
  const { activeScreen, setActiveScreen, loadProvenance, loadFixtureJob } = useStore()

  // Load provenance and fixture job on mount so all screens have data
  useEffect(() => {
    loadProvenance()
    loadFixtureJob()
  }, [])

  const renderScreen = () => {
    switch (activeScreen) {
      case 'system':     return <SystemScreen />
      case 'detail':     return <CandidateDetail />
      case 'chat':       return <ChatPanel />
      case 'upload':     return <UploadFlow />
      case 'training':   return <TrainingSandbox />
      case 'provenance': return <ProvenancePage />
      case 'console':    return <LiveConsole />
      default:           return <SystemScreen />
    }
  }

  return (
    <div className="app-shell">
      {/* Top navigation */}
      <nav className="top-nav" role="navigation" aria-label="Main navigation">
        <div className="logo">
          <span>Falsifier</span>
        </div>
        {SCREENS.map((s) => (
          <button
            key={s.id}
            className={`nav-btn${activeScreen === s.id ? ' active' : ''}`}
            onClick={() => setActiveScreen(s.id)}
            aria-current={activeScreen === s.id ? 'page' : undefined}
            title={s.title}
          >
            {s.label}
          </button>
        ))}
      </nav>

      {/* Active screen */}
      <main className="screen" style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        {renderScreen()}
      </main>

      {/* Page footer — locked non-claim on every page */}
      <footer className="page-footer" role="contentinfo">
        {LOCKED_NON_CLAIM}
      </footer>
    </div>
  )
}
