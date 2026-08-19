/**
 * src/App.tsx
 * Root application shell: newspaper masthead, dateline, nav, screens, locked footer.
 * All scientific values flow from the data layer — no literals here.
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
  { id: 'system',     label: 'Investigate',  title: 'Landing / investigate a target' },
  { id: 'detail',     label: 'Report',        title: 'Full candidate report' },
  { id: 'chat',       label: 'Ask',           title: 'Pipeline chat' },
  { id: 'upload',     label: 'Upload',        title: 'Light curve upload' },
  { id: 'training',   label: 'Training',      title: 'Training sandbox' },
  { id: 'provenance', label: 'Provenance',    title: 'Data provenance' },
  { id: 'console',    label: 'Console',       title: 'Live console' },
]

const LOCKED_NON_CLAIM =
  'Not a biosignature detector · No exoplanet biosignature has ever been confirmed · ' +
  'Classifier probability is a ranking score only — not a verdict'

export default function App() {
  const { activeScreen, setActiveScreen, loadProvenance, loadFixtureJob } = useStore()

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
      {/* Header wrapper — constrains all header elements to the same column */}
      <div className="header-wrap">
        <div className="header-inner">

          {/* Newspaper masthead — reduced wordmark */}
          <header className="masthead" role="banner">
            <div className="masthead-title" aria-label="Falsifier">FALSIFIER</div>
          </header>

          {/* 1px rule directly under wordmark */}
          <hr className="masthead-rule-thin" />

          {/* Dateline strip — four items spanning full container width */}
          <div className="dateline" role="doc-subtitle">
            <span className="dateline-item">FALSE-POSITIVE TRIAGE</span>
            <span className="dateline-item">KEPLER · K2 · TESS</span>
            <span className="dateline-item">NO API KEYS</span>
            <span className="dateline-item">OPEN ARTIFACTS</span>
          </div>

          {/* 3px double rule closing the masthead block */}
          <hr className="masthead-rule-double" />

          {/* Navigation — centered under the masthead */}
          <nav className="top-nav" role="navigation" aria-label="Main navigation">
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

        </div>
      </div>

      {/* Active screen */}
      <main className="screen" role="main">
        {renderScreen()}
      </main>

      {/* Page footer — locked non-claim on every page */}
      <footer className="page-footer" role="contentinfo">
        {LOCKED_NON_CLAIM}
      </footer>
    </div>
  )
}
