import { useCallback, useEffect, useState } from 'react'
import { getBusinessCases, getDashboard, getDatasets, getOpportunities } from './api'
import BusinessCases from './components/BusinessCases'
import Dashboard from './components/Dashboard'
import DataSources from './components/DataSources'
import Opportunities from './components/Opportunities'
import Tracking from './components/Tracking'
import type {
  BusinessCase,
  DashboardData,
  Opportunity,
  PrioritizationSummary,
  SourceStatus,
  Weights,
} from './types'

type Tab = 'overview' | 'sources' | 'opportunities' | 'cases' | 'tracking'

const DEFAULT_WEIGHTS: Weights = { value: 35, efficiency: 30, speed: 15, simplicity: 20 }

export default function App() {
  const [tab, setTab] = useState<Tab>('overview')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
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
          Innovation<span className="accent">Value</span>Dashboard
        </h1>
        <nav>
          <button className={tab === 'overview' ? 'active' : ''} onClick={() => setTab('overview')}>
            Overview
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
        </nav>
      </header>

      {offline && (
        <div className="banner-error">
          Cannot reach the API. Start it with:{' '}
          <code>cd server && uvicorn app.main:app --port 8000</code>
        </div>
      )}

      <main>
        {tab === 'overview' && <Dashboard data={dashboard} onNavigate={setTab} />}
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
      </main>
    </div>
  )
}
