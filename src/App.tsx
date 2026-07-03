import { useCallback, useEffect, useState } from 'react'
import { searchAll, getMe, login, logout, demoRevert, getBusinessCases, getDashboard, getDatasets, getDemoStatus, getIdeas, getOpportunities, getPortfolioDiagnostic } from './api'
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

interface AuthUser { name: string; role: string }

function LoginScreen({ onDone }: { onDone: (u: AuthUser) => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="login-screen">
      <div className="card login-card">
        <h1>Innovation<span className="accent">Hub</span></h1>
        <p className="muted small">
          Sign in to continue. If no accounts exist yet, your first sign-in creates
          the admin account.
        </p>
        <input placeholder="User ID" value={name} autoFocus
               onChange={(e) => setName(e.target.value)} />
        <input type="password" placeholder="Password" value={password}
               onChange={(e) => setPassword(e.target.value)}
               onKeyDown={(e) => e.key === 'Enter' && name && password && submit()} />
        <button disabled={busy || !name.trim() || !password} onClick={() => submit()}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  )
  async function submit() {
    setBusy(true); setError(null)
    try {
      onDone(await login(name, password))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally { setBusy(false) }
  }
}

function ProfileMenu({ me, onChangeUser }: { me: AuthUser | null; onChangeUser: () => void }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="profile-menu">
      <button className="profile-fab" aria-label="User profile" aria-expanded={open}
              onClick={() => setOpen(!open)}>
        {me ? me.name.slice(0, 2).toUpperCase() : '👤'}
      </button>
      {open && (
        <div className="card profile-pop">
          {me ? (
            <>
              <p><span className="muted small">User ID</span><br /><strong>{me.name}</strong></p>
              <p><span className="muted small">Role</span><br />
                <span className="pill act-approve">{me.role}</span></p>
              <button className="secondary" onClick={() => { setOpen(false); onChangeUser() }}>
                Change user
              </button>
            </>
          ) : (
            <>
              <p className="muted small">
                Not signed in — the hub is open until user profiles exist.
              </p>
              <button onClick={() => { setOpen(false); onChangeUser() }}>Sign in</button>
            </>
          )}
        </div>
      )}
    </div>
  )
}

export default function App() {
  const [me, setMe] = useState<AuthUser | null>(null)
  const [authRequired, setAuthRequired] = useState(false)
  const [authChecked, setAuthChecked] = useState(false)
  const [wantLogin, setWantLogin] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<{ type: string; tab: string; id: string; title: string; hint: string }[]>([])
  const searchTimer = (window as unknown as { __ivdT?: number })
  const runSearch = (q: string) => {
    setQuery(q)
    if (searchTimer.__ivdT) window.clearTimeout(searchTimer.__ivdT)
    if (q.trim().length < 2) { setHits([]); return }
    searchTimer.__ivdT = window.setTimeout(() => {
      searchAll(q).then((r) => setHits(r.results)).catch(() => {})
    }, 350)
  }
  const [collapsed, setCollapsed] = useState(localStorage.getItem('ivd_nav') === 'collapsed')
  const [tab, setTab] = useState<Tab>('overview')
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
    getMe()
      .then((r) => { setAuthRequired(r.auth_required); setMe(r.user) })
      .catch(() => {})
      .finally(() => setAuthChecked(true))
    const onAuthRequired = () => { setAuthRequired(true); setMe(null) }
    window.addEventListener('ivd-auth-required', onAuthRequired)
    return () => window.removeEventListener('ivd-auth-required', onAuthRequired)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const changeUser = async () => {
    await logout()
    setMe(null)
    setWantLogin(true)
  }

  if (!authChecked) return null
  if (wantLogin || (authRequired && !me)) {
    return (
      <LoginScreen onDone={(u) => {
        setMe(u); setAuthRequired(true); setWantLogin(false); refresh()
      }} />
    )
  }

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
        {!collapsed && (
          <div className="nav-search">
            <input placeholder="Search…" value={query}
                   onChange={(e) => runSearch(e.target.value)} aria-label="Global search" />
            {hits.length > 0 && (
              <div className="search-results">
                {hits.map((h) => (
                  <button key={`${h.type}-${h.id}`} onClick={() => {
                    setTab(h.tab as Tab); setHits([]); setQuery('')
                  }}>
                    <span className="tag">{h.type}</span> {h.title}
                    <span className="muted small"> {h.hint}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
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
      <ProfileMenu me={me} onChangeUser={changeUser} />
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

      <main>
        {tab === 'overview' && <Dashboard data={dashboard} onNavigate={setTab} onChanged={refresh} />}
        {tab === 'ideas' && <Ideas ideas={ideas} onChanged={refresh} />}
        {tab === 'command' && <CommandCenter onChanged={refresh} />}
        {tab === 'pipeline' && <PipelineView />}
        {tab === 'settings' && <Settings onChanged={refresh} />}
        {tab === 'mine' && <MySubmissions me={me} />}
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
