import { useCallback, useEffect, useState } from 'react'
import { demoRevert, getBusinessCases, getDashboard, getDatasets, getDemoStatus, getIdeas, getOpportunities, getPortfolioDiagnostic } from './api'
import BusinessCases from './components/BusinessCases'
import CommandCenter from './components/CommandCenter'
import Dashboard from './components/Dashboard'
import DataSources from './components/DataSources'
import Ideas from './components/Ideas'
import Opportunities from './components/Opportunities'
import MySubmissions from './components/MySubmissions'
import PipelineView from './components/PipelineView'
import Settings from './components/Settings'
import Portfolio from './components/Portfolio'
import Tracking from './components/Tracking'
import type {
  BusinessCase,
  DashboardData,
  DemoStatus,
  Idea,
  Opportunity,
  PortfolioReport,
  PrioritizationSummary,
  SourceStatus,
  Weights,
} from './types'

type Tab =
  | 'overview' | 'ideas' | 'command' | 'pipeline' | 'sources'
  | 'opportunities' | 'cases' | 'tracking' | 'portfolio' | 'settings' | 'mine'

const DEFAULT_WEIGHTS: Weights = { value: 35, efficiency: 30, speed: 15, simplicity: 20 }

const ROLE_TAB: Record<string, Tab> = {
  contributor: 'ideas',
  reviewer: 'command',
  executive: 'overview',
}

export default function App() {
  const storedRole = localStorage.getItem('ivd_role')
  const [role, setRole] = useState<string | null>(storedRole)
  const [collapsed, setCollapsed] = useState(localStorage.getItem('ivd_nav') === 'collapsed')
  const [tab, setTab] = useState<Tab>(storedRole ? (ROLE_TAB[storedRole] ?? 'overview') : 'overview')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [portfolioReport, setPortfolioReport] = useState<PortfolioReport | null>(null)
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [demoStatus, setDemoStatus] = useState<DemoStatus | null>(null)
  const [sources, setSources] = useState<SourceStatus[]>([])
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<PrioritizationSummary | null>(null)
  const [weights, setWeights] = useState<Weights>(DEFAULT_WEIGHTS)
  const [cases, setCases] = useState<BusinessCase[]>([])
  const [offline, setOffline] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [ds, opps, bcs, dash] = await Promise.all([
        getDatasets(),
        getOpportunities(weights),
        getBusinessCases(),
        getDashboard(),
      ])
      setSources(ds.sources)
      setDashboard(dash)
      setOpportunities(opps.opportunities)
      setTotal(opps.total_estimated_annual_savings)
      setSummary(opps.prioritization.summary)
      setCases(bcs.business_cases)
      setIdeas((await getIdeas().catch(() => ({ ideas: [] }))).ideas)
      setDemoStatus((await getDemoStatus().catch(() => ({ demo: null, industries: [] }))).demo)
      setPortfolioReport(await getPortfolioDiagnostic().catch(() => null))
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [weights])

  useEffect(() => {
    refresh()
  }, [refresh])

  const hasData = sources.some((s) => s.rows_loaded > 0)

  const NAV: [Tab, string, string][] = [
    ['overview', '◉', 'Overview'],
    ['ideas', '✎', 'Idea Submission'],
    ['mine', '★', 'My Submissions'],
    ['command', '⌘', 'Command Center'],
    ['pipeline', '⇶', 'Pipeline'],
    ['sources', '⛁', 'Data Sources'],
    ['opportunities', '◎', 'Opportunities'],
    ['cases', '▤', 'Business Cases'],
    ['tracking', '✓', 'ROI Tracking'],
    ['portfolio', '▦', 'Portfolio'],
    ['settings', '⚙', 'Hub Settings'],
  ]

  return (
    <div className={`shell ${collapsed ? 'nav-collapsed' : ''}`}>
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand">
          <h1>{collapsed ? <span className="accent">IH</span> : <>Innovation<span className="accent">Hub</span></>}</h1>
          <button
            className="collapse-toggle" aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'}
            onClick={() => {
              const next = !collapsed
              setCollapsed(next)
              localStorage.setItem('ivd_nav', next ? 'collapsed' : 'open')
            }}
          >
            {collapsed ? '»' : '«'}
          </button>
        </div>
        <nav>
          {NAV.map(([id, glyph, label]) => (
            <button key={id} className={tab === id ? 'active' : ''} title={label}
                    onClick={() => setTab(id)}>
              <span className="nav-glyph" aria-hidden="true">{glyph}</span>
              <span className="nav-label">{label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <div className="content">
      {demoStatus && (
        <div className="banner-demo">
          <span>
            <strong>Demo portfolio active:</strong> {demoStatus.client} ({demoStatus.industry}) —
            data shown is illustrative for this presentation.
          </span>
          <button
            className="secondary"
            onClick={async () => {
              await demoRevert().catch(() => {})
              refresh()
            }}
          >
            Revert to baseline
          </button>
        </div>
      )}

      {offline && (
        <div className="banner-error">
          <span>
            <strong>Reconnecting…</strong> The hub can't reach its data service right now — this
            usually resolves in a few seconds.
          </span>
          <button className="secondary" onClick={refresh}>Retry now</button>
        </div>
      )}

      {!role && (
        <div className="role-picker card">
          <h2>Welcome to the Innovation Hub — what brings you here?</h2>
          <div className="role-options">
            {[
              ['contributor', 'I have an idea', 'Share it in two minutes — the hub does the paperwork.'],
              ['reviewer', 'I review and decide', 'Your approval queue, experiments, and governance.'],
              ['executive', 'I want the value picture', 'Verified ROI, trajectory, and decisions on the table.'],
            ].map(([id, label, hint]) => (
              <button
                key={id}
                className="role-option"
                onClick={() => {
                  localStorage.setItem('ivd_role', id)
                  setRole(id)
                  setTab(ROLE_TAB[id])
                }}
              >
                <strong>{label}</strong>
                <span className="muted small">{hint}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <main>
        {tab === 'overview' && <Dashboard data={dashboard} onNavigate={setTab} onChanged={refresh} />}
        {tab === 'ideas' && <Ideas ideas={ideas} onChanged={refresh} />}
        {tab === 'command' && <CommandCenter onChanged={refresh} />}
        {tab === 'pipeline' && <PipelineView />}
        {tab === 'settings' && <Settings onChanged={refresh} />}
        {tab === 'mine' && <MySubmissions />}
        {tab === 'sources' && <DataSources sources={sources} onChanged={refresh} />}
        {tab === 'opportunities' && (
          <Opportunities
            opportunities={opportunities}
            total={total}
            summary={summary}
            weights={weights}
            onWeightsChange={setWeights}
            hasData={hasData}
          />
        )}
        {tab === 'cases' && (
          <BusinessCases cases={cases} opportunities={opportunities} onChanged={refresh} />
        )}
        {tab === 'tracking' && <Tracking cases={cases} onChanged={refresh} />}
        {tab === 'portfolio' && (
          <Portfolio
            report={portfolioReport}
            hasPortfolio={sources.some((s) => s.source_type === 'portfolio' && s.rows_loaded > 0)}
            onChanged={refresh}
          />
        )}
      </main>
      </div>
    </div>
  )
}
