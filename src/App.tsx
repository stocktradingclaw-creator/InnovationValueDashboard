import { useCallback, useEffect, useState } from 'react'
import { getBusinessCases, getDashboard, getDatasets, getIdeas, getOpportunities, getPortfolioDiagnostic } from './api'
import BusinessCases from './components/BusinessCases'
import CommandCenter from './components/CommandCenter'
import Dashboard from './components/Dashboard'
import DataSources from './components/DataSources'
import Ideas from './components/Ideas'
import Opportunities from './components/Opportunities'
import Portfolio from './components/Portfolio'
import Tracking from './components/Tracking'
import type {
  BusinessCase,
  DashboardData,
  Idea,
  Opportunity,
  PortfolioReport,
  PrioritizationSummary,
  SourceStatus,
  Weights,
} from './types'

type Tab =
  | 'overview' | 'ideas' | 'command' | 'sources'
  | 'opportunities' | 'cases' | 'tracking' | 'portfolio'

const DEFAULT_WEIGHTS: Weights = { value: 35, efficiency: 30, speed: 15, simplicity: 20 }

const ROLE_TAB: Record<string, Tab> = {
  contributor: 'ideas',
  reviewer: 'command',
  executive: 'overview',
}

export default function App() {
  const storedRole = localStorage.getItem('ivd_role')
  const [role, setRole] = useState<string | null>(storedRole)
  const [tab, setTab] = useState<Tab>(storedRole ? (ROLE_TAB[storedRole] ?? 'overview') : 'overview')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [portfolioReport, setPortfolioReport] = useState<PortfolioReport | null>(null)
  const [ideas, setIdeas] = useState<Idea[]>([])
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

  return (
    <div className="app">
      <header>
        <h1>
          Innovation<span className="accent">Hub</span>
        </h1>
        <nav>
          <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>
            Overview
          </button>
          <button className={tab === 'ideas' ? 'active' : ''} onClick={() => setTab('ideas')}>
            Ideas{ideas.length > 0 && ` (${ideas.length})`}
          </button>
          <button className={tab === 'command' ? 'active' : ''} onClick={() => setTab('command')}>
            Command Center
          </button>
          <button className={tab === 'sources' ? 'active' : ''} onClick={() => setTab('sources')}>
            Data Sources
          </button>
          <button
            className={tab === 'opportunities' ? 'active' : ''}
            onClick={() => setTab('opportunities')}
          >
            Opportunities{opportunities.length > 0 && ` (${opportunities.length})`}
          </button>
          <button className={tab === 'cases' ? 'active' : ''} onClick={() => setTab('cases')}>
            Business Cases{cases.length > 0 && ` (${cases.length})`}
          </button>
          <button className={tab === 'tracking' ? 'active' : ''} onClick={() => setTab('tracking')}>
            ROI Tracking
          </button>
          <button className={tab === 'portfolio' ? 'active' : ''} onClick={() => setTab('portfolio')}>
            Portfolio
          </button>
        </nav>
      </header>

      {offline && (
        <div className="banner-error">
          Cannot reach the API. Start it with:{' '}
          <code>cd server && uvicorn app.main:app --port 8000</code>
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
  )
}
