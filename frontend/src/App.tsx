/**
 * src/App.tsx
 * Root application shell: newspaper masthead, dateline, nav, screens.
 * All scientific values flow from the data layer — no literals here.
 *
 * Screen order (judge path first, then secondary):
 *   Primary: Investigate → Report → Gates → Try to break it → Judge
 *   Secondary: Ask · Upload · Training · Provenance · Console
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
import JudgePage from './screens/JudgePage'
import GatesScreen from './screens/GatesScreen'
import AdversarialPanel from './screens/AdversarialPanel'

// Primary screens (judge path): shown prominently in nav
const PRIMARY_SCREENS = [
  { id: 'system',      label: 'Investigate',   title: 'Enter a target ID and run the pipeline' },
  { id: 'detail',      label: 'Report',         title: 'Full candidate report' },
  { id: 'adversarial', label: 'Try to break it',title: 'Adversarial self-test — null data false-alarm demo' },
  { id: 'gates',       label: 'Gates',          title: 'Defect log + mutation testing gates' },
  { id: 'judge',       label: 'Judge ✓',        title: 'Judge verification walkthrough' },
]

// Secondary screens: all other tools
const SECONDARY_SCREENS = [
  { id: 'chat',        label: 'Ask',            title: 'Pipeline chat' },
  { id: 'upload',      label: 'Upload',         title: 'Light curve upload' },
  { id: 'training',    label: 'Training',       title: 'Training sandbox' },
  { id: 'provenance',  label: 'Provenance',     title: 'Data provenance' },
  { id: 'console',     label: 'Console',        title: 'Live console' },
]

const SCREENS = [...PRIMARY_SCREENS, ...SECONDARY_SCREENS]

export default function App() {
  const { activeScreen, setActiveScreen, loadProvenance, rehydrateJob } = useStore()

  useEffect(() => {
    loadProvenance()
    rehydrateJob()
  }, [])

  const renderScreen = () => {
    switch (activeScreen) {
      case 'system':      return <SystemScreen />
      case 'detail':      return <CandidateDetail />
      case 'chat':        return <ChatPanel />
      case 'upload':      return <UploadFlow />
      case 'training':    return <TrainingSandbox />
      case 'provenance':  return <ProvenancePage />
      case 'console':     return <LiveConsole />
      case 'judge':       return <JudgePage />
      case 'gates':       return <GatesScreen />
      case 'adversarial': return <AdversarialPanel />
      default:            return <SystemScreen />
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

          {/* Navigation — primary path first, then secondary */}
          <nav className="top-nav" role="navigation" aria-label="Main navigation">
            {PRIMARY_SCREENS.map((s) => (
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
            <span style={{ width: 1, background: 'var(--np-border)', alignSelf: 'stretch', margin: '0 4px' }} aria-hidden="true" />
            {SECONDARY_SCREENS.map((s) => (
              <button
                key={s.id}
                className={`nav-btn${activeScreen === s.id ? ' active' : ''}` + ' secondary'}
                onClick={() => setActiveScreen(s.id)}
                aria-current={activeScreen === s.id ? 'page' : undefined}
                title={s.title}
                style={{ opacity: 0.75 }}
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
    </div>
  )
}
