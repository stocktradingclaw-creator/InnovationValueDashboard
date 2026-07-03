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

const ICONS: Record<string, string> = {
  overview: 'M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  mine: 'M12 3l2.6 5.6 6.4.8-4.7 4.3 1.2 6.3-5.5-3.2-5.5 3.2 1.2-6.3L3 9.4l6.4-.8z',
  command: 'M4 4h16v16H4zM8 12l3 3 5-6',
  pipeline: 'M4 6h10M4 12h16M4 18h7M18 4l3 3-3 3',
  opportunities: 'M12 3a9 9 0 109 9M12 8a4 4 0 104 4M12 12h.01',
  cases: 'M4 5h16v14H4zM4 10h16M9 5v14',
  tracking: 'M4 17l5-5 4 3 7-8M16 7h4v4',
  portfolio: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  sources: 'M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3zM4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6',
  settings: 'M12 8a4 4 0 100 8 4 4 0 000-8zM19 12l2 1-1 3-2.3-.3a7 7 0 01-1.6 1.6L16 20h-3l-.3-2.3a7 7 0 01-1.6-1.6L8 17l-1-3 2-1-2-1 1-3 2.3.3a7 7 0 011.6-1.6L13 4h3l.3 2.3a7 7 0 011.6 1.6L20 8l1 3z',
  plus: 'M12 5v14M5 12h14',
}

function Icon({ name }: { name: string }) {
  return (
    <svg className="nav-glyph" viewBox="0 0 24 24" width="16" height="16" fill="none"
         stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"
         aria-hidden="true">
      <path d={ICONS[name] ?? ICONS.overview} />
    </svg>
  )
}

interface AuthUser { name: string; role: string }

function LoginScreen({ onDone }: { onDone: (u: AuthUser) => void }) {
  const [name, setName] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  return (
    <div className="login-screen">
      <div className="card login-card">
        <svg viewBox="0 0 24 24" width="44" height="44" aria-hidden="true" className="login-mark">
          <rect width="24" height="24" rx="6" fill="var(--surface-2)" />
          <path d="M7 16l4-5 3 2 4-6" stroke="var(--accent)" strokeWidth="2.2" fill="none" strokeLinecap="round" />
        </svg>
        <h1>Innovation<span className="accent">Hub</span></h1>
        <p className="muted small">
          Welcome back — sign in to pick up where you left off.
          First time here? Your first sign-in creates the admin account.
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

function Toasts() {
  const [toasts, setToasts] = useState<{ id: number; msg: string; undo?: () => void }[]>([])
  useEffect(() => {
    const h = (e: Event) => {
      const d = (e as CustomEvent).detail as { msg: string; undo?: () => void }
      const id = Date.now() + Math.random()
      setToasts((t) => [...t, { id, ...d }])
      window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), d.undo ? 8000 : 4000)
    }
    window.addEventListener('ivd-toast', h)
    return () => window.removeEventListener('ivd-toast', h)
  }, [])
  if (toasts.length === 0) return null
  return (
    <div className="toasts" role="status" aria-live="polite">
      {toasts.map((t) => (
        <div key={t.id} className="toast">
          {t.msg}
          {t.undo && (
            <button onClick={() => { t.undo!(); setToasts((x) => x.filter((y) => y.id !== t.id)) }}>
              Undo
            </button>
          )}
        </div>
      ))}
    </div>
  )
}

function ProfileMenu({ me, onChangeUser }: { me: AuthUser | null; onChangeUser: () => void }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const close = (e: Event) => {
      if (e instanceof KeyboardEvent && e.key !== 'Escape') return
      if (e instanceof MouseEvent && (e.target as HTMLElement).closest('.profile-menu')) return
      setOpen(false)
    }
    document.addEventListener('keydown', close)
    document.addEventListener('mousedown', close)
    return () => { document.removeEventListener('keydown', close); document.removeEventListener('mousedown', close) }
  }, [open])
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
  const [hitIndex, setHitIndex] = useState(-1)
  const runSearch = (q: string) => {
    setQuery(q)
    setHitIndex(-1)
    if (searchTimer.__ivdT) window.clearTimeout(searchTimer.__ivdT)
    if (q.trim().length < 2) { setHits([]); return }
    searchTimer.__ivdT = window.setTimeout(() => {
      searchAll(q).then((r) => setHits(r.results)).catch(() => {})
    }, 350)
  }
  const pickHit = (h: { tab: string }) => { setTab(h.tab as Tab); setHits([]); setQuery('') }
  const searchKeys = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setHitIndex((i) => Math.min(i + 1, hits.length - 1)) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHitIndex((i) => Math.max(i - 1, 0)) }
    else if (e.key === 'Enter' && hitIndex >= 0 && hits[hitIndex]) pickHit(hits[hitIndex])
    else if (e.key === 'Escape') { setHits([]); setQuery('') }
  }
  const searchBlock = (
    <div className="nav-search">
      <input placeholder="Search…" value={query} role="combobox" aria-expanded={hits.length > 0}
             aria-controls="ivd-search-results" aria-activedescendant={hitIndex >= 0 ? `hit-${hitIndex}` : undefined}
             onChange={(e) => runSearch(e.target.value)} onKeyDown={searchKeys}
             aria-label="Global search" />
      {hits.length > 0 && (
        <div className="search-results" id="ivd-search-results" role="listbox">
          {hits.map((h, i) => (
            <button key={`${h.type}-${h.id}`} id={`hit-${i}`} role="option"
                    aria-selected={i === hitIndex}
                    className={i === hitIndex ? 'hit-active' : ''}
                    onClick={() => pickHit(h)}>
              <span className="tag">{h.type}</span> {h.title}
              <span className="muted small"> {h.hint}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
  const [collapsed, setCollapsed] = useState(localStorage.getItem('ivd_nav') === 'collapsed')
  const [tab, setTab] = useState<Tab>('overview')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [portfolioReport, setPortfolioReport] = useState<PortfolioReport | null>(null)
  const [ideas, setIdeas] = useState<Idea[]>([])
  const [demoStatus, setDemoStatus] = useState<DemoStatus | null>(null)
  const [seeded, setSeeded] = useState(false)
  const [needsMe, setNeedsMe] = useState(0)
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
      const demoState = await getDemoStatus().catch(() => ({ demo: null, industries: [], seeded: false }))
      setDemoStatus(demoState.demo)
      setSeeded(Boolean((demoState as { seeded?: boolean }).seeded))
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
    const onNav = (e: Event) => setTab((e as CustomEvent).detail as Tab)
    const who = localStorage.getItem('ivd_user')
    if (who) {
      import('./api').then(({ getMyWork }) =>
        getMyWork(who).then((r) => setNeedsMe(r.items.filter((i) => i.kind === 'respond').length))
          .catch(() => {}))
    }
    window.addEventListener('ivd-auth-required', onAuthRequired)
    window.addEventListener('ivd-nav', onNav)
    return () => {
      window.removeEventListener('ivd-auth-required', onAuthRequired)
      window.removeEventListener('ivd-nav', onNav)
    }
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

  const NAV_GROUPS: [string, [Tab, string, string][]][] = [
    ['My work', [
      ['overview', '⌂', 'Overview'],
      ['mine', '★', 'My Submissions'],
    ]],
    ['Decide', [
      ['command', '☑', 'Approvals'],
      ['pipeline', '≫', 'Pipeline'],
    ]],
    ['Value', [
      ['opportunities', '◎', 'Opportunities'],
      ['cases', '▤', 'Business Cases'],
      ['tracking', '✓', 'ROI Tracking'],
      ['portfolio', '▦', 'Portfolio'],
    ]],
    ['Configure', [
      ['sources', '⛁', 'Data Sources'],
      ['settings', '⚙', 'Hub Settings'],
    ]],
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
        {!collapsed && searchBlock}
        <button className="new-idea-cta" onClick={() => setTab('ideas')}
                title="Submit a new idea">
          <Icon name="plus" />
          <span className="nav-label">New idea</span>
        </button>
        <nav>
          {NAV_GROUPS.map(([group, items]) => (
            <div key={group} className="nav-group">
              <span className="nav-group-label nav-label">{group}</span>
              {items.map(([id, , label]) => (
                <button key={id} className={tab === id ? 'active' : ''} title={label}
                        onClick={() => setTab(id)}>
                  <Icon name={id} />
                  <span className="nav-label">{label}</span>
                  {id === 'mine' && needsMe > 0 && (
                    <span className="nav-dot" title={`${needsMe} item(s) need your response`}>
                      {needsMe}
                    </span>
                  )}
                </button>
              ))}
            </div>
          ))}
        </nav>
      </aside>
      <div className="content">
      <Toasts />
      <div className="mobile-search">{searchBlock}</div>
      <ProfileMenu me={me} onChangeUser={changeUser} />
      {!demoStatus && seeded && !localStorage.getItem('ivd_seed_ack') && (
        <div className="banner-demo">
          <span>
            <strong>You're looking at sample data</strong> — a full portfolio seeded across
            every lifecycle phase so you can explore. Make it yours anytime.
          </span>
          <button className="secondary" onClick={() => {
            localStorage.setItem('ivd_seed_ack', '1'); refresh()
          }}>Got it</button>
        </div>
      )}
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
