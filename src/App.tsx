import { useCallback, useEffect, useState } from 'react'
import { getBusinessCases, getDatasets, getOpportunities } from './api'
import BusinessCases from './components/BusinessCases'
import DataSources from './components/DataSources'
import Opportunities from './components/Opportunities'
import type { BusinessCase, Opportunity, SourceStatus } from './types'

type Tab = 'sources' | 'opportunities' | 'cases'

export default function App() {
  const [tab, setTab] = useState<Tab>('sources')
  const [sources, setSources] = useState<SourceStatus[]>([])
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [total, setTotal] = useState(0)
  const [cases, setCases] = useState<BusinessCase[]>([])
  const [offline, setOffline] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [ds, opps, bcs] = await Promise.all([
        getDatasets(),
        getOpportunities(),
        getBusinessCases(),
      ])
      setSources(ds.sources)
      setOpportunities(opps.opportunities)
      setTotal(opps.total_estimated_annual_savings)
      setCases(bcs.business_cases)
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

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
        </nav>
      </header>

      {offline && (
        <div className="banner-error">
          Cannot reach the API. Start it with:{' '}
          <code>cd server && uvicorn app.main:app --port 8000</code>
        </div>
      )}

      <main>
        {tab === 'sources' && <DataSources sources={sources} onChanged={refresh} />}
        {tab === 'opportunities' && (
          <Opportunities opportunities={opportunities} total={total} hasData={hasData} />
        )}
        {tab === 'cases' && <BusinessCases cases={cases} onChanged={refresh} />}
      </main>
    </div>
  )
}
