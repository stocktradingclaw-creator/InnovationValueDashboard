import { useCallback, useEffect, useState } from 'react'
import { searchAll, getMe, login, logout, demoRevert, getBusinessCases, getDashboard, getDatasets, getDemoStatus, getIdeas, getOpportunities, getPortfolioDiagnostic } from './api'
import BusinessCases from './components/BusinessCases'
import Campaigns from './components/Campaigns'
import CommandCenter from './components/CommandCenter'
import Dashboard from './components/Dashboard'
import DataSources from './components/DataSources'
import Ideas from './components/Ideas'
import Ideate from './components/Ideate'
import Opportunities from './components/Opportunities'
import Maturity from './components/Maturity'
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
} from './types'

type Tab =
  | 'overview' | 'ideas' | 'command' | 'pipeline' | 'sources'
  | 'opportunities' | 'cases' | 'tracking' | 'portfolio' | 'settings' | 'mine' | 'campaigns' | 'ideate-futures' | 'ideate-competitive' | 'ideate-maturity' | 'ideate-workshops' | 'ideate-tentypes' | 'ideate-funnel'

const ICONS: Record<string, string> = {
  overview: 'M3 12l9-8 9 8M5 10v10h5v-6h4v6h5V10',
  mine: 'M12 3l2.6 5.6 6.4.8-4.7 4.3 1.2 6.3-5.5-3.2-5.5 3.2 1.2-6.3L3 9.4l6.4-.8z',
  command: 'M4 4h16v16H4zM8 12l3 3 5-6',
  'ideate-futures': 'M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M12 8a4 4 0 100 8 4 4 0 000-8z',
  'ideate-competitive': 'M6 3l12 12M18 3L6 15M4 21l4-1 1-4M20 21l-4-1-1-4',
  'ideate-maturity': 'M4 20V10M9 20V6M14 20v-8M19 20V4',
  'ideate-workshops': 'M4 5h16v11H4zM8 21h8M12 16v5',
  'ideate-funnel': 'M4 4h16l-6 8v6l-4 2v-8L4 4z',
  'ideate-tentypes': 'M12 3a9 9 0 11-9 9M12 7v5l3 3',
  ideate: 'M12 3a6 6 0 00-4 10c.8.8 1 1.4 1 2h6c0-.6.2-1.2 1-2a6 6 0 00-4-10zM9 18h6M10 21h4',
  campaigns: 'M3 11l14-5v12L3 13v-2zM17 8a3 3 0 010 8M7 13v6h3v-5',
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
  const [requested, setRequested] = useState(false)
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
        <button className="secondary" disabled={!name.trim() || requested} onClick={async () => {
          const { requestAccess } = await import('./api')
          const r = await requestAccess(name).catch(() => null)
          setRequested(true)
          setError(r ? `Request sent — ${r.admins_notified} admin(s) notified. They'll add you in Hub Settings.` : 'Could not send the request.')
        }}>{requested ? 'Request sent ✓' : 'No account? Request access'}</button>
        {error && <p className={requested ? 'success' : 'error'}>{error}</p>}
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

function StartScreen({ onDone, onCancel }: { onDone: (u: AuthUser) => void; onCancel: () => void }) {
  const [name, setName] = useState('')
  const [company, setCompany] = useState('')
  const [email, setEmail] = useState('')
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
        <h1>Start your <span className="accent">workspace</span></h1>
        <p className="muted small">
          Clears the sample data and makes you the admin — your ideas, your
          numbers, verified from your data.
        </p>
        <input placeholder="Your name" value={name} autoFocus onChange={(e) => setName(e.target.value)} />
        <input placeholder="Company" value={company} onChange={(e) => setCompany(e.target.value)} />
        <input type="email" placeholder="Work email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input type="password" placeholder="Choose a password" value={password}
               onChange={(e) => setPassword(e.target.value)} />
        <button disabled={busy || !name.trim() || !company.trim() || !email.includes('@') || !password} onClick={async () => {
          setBusy(true); setError(null)
          try {
            const res = await fetch('/api/workspace/start', {
              method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ name, company, email, password }),
            })
            const d = await res.json()
            if (!res.ok) throw new Error(d.detail ?? 'could not start workspace')
            localStorage.setItem('ivd_token', d.token)
            localStorage.setItem('ivd_user', d.user.name)
            onDone(d.user)
          } catch (e) { setError(e instanceof Error ? e.message : String(e)) }
          finally { setBusy(false) }
        }}>{busy ? 'Creating…' : 'Create workspace — free'}</button>
        <button className="secondary" onClick={onCancel}>Keep exploring the demo</button>
        {error && <p className="error">{error}</p>}
      </div>
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
  const [wantStart, setWantStart] = useState(false)
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
  const pickHit = (h: { tab: string; id: string }) => {
    setTab(h.tab as Tab); setHits([]); setQuery('')
    window.setTimeout(() => {
      const el = document.querySelector(`[data-eid="${h.id}"]`)
      if (el) {
        el.scrollIntoView({ behavior: 'smooth', block: 'center' })
        el.classList.add('flash')
        window.setTimeout(() => el.classList.remove('flash'), 2400)
      }
    }, 450)
  }
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
  const [workspace, setWorkspace] = useState<string | null>(null)
  const [sources, setSources] = useState<SourceStatus[]>([])
  const [opportunities, setOpportunities] = useState<Opportunity[]>([])
  const [total, setTotal] = useState(0)
  const [summary, setSummary] = useState<PrioritizationSummary | null>(null)
  const [cases, setCases] = useState<BusinessCase[]>([])
  const [offline, setOffline] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [ds, opps, bcs, dash] = await Promise.all([
        getDatasets(),
        getOpportunities(),
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
  }, [])

  useEffect(() => {
    getMe()
      .then((r) => { setAuthRequired(r.auth_required); setMe(r.user); setWorkspace((r as { workspace?: string }).workspace ?? null); if (r.user) localStorage.setItem('ivd_role', r.user.role) })
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
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setCollapsed(false)
        window.setTimeout(() => {
          (document.querySelector('.nav-search input') as HTMLInputElement | null)?.focus()
        }, 50)
      }
    }
    window.addEventListener('keydown', onKey)
    window.addEventListener('ivd-nav', onNav)
    return () => {
      window.removeEventListener('ivd-auth-required', onAuthRequired)
      window.removeEventListener('keydown', onKey)
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
  if (wantStart) {
    return <StartScreen onCancel={() => setWantStart(false)} onDone={(u) => {
      setMe(u); setAuthRequired(true); setWantStart(false); refresh()
    }} />
  }
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
    ['Ideate', [
      ['opportunities', '◎', 'Detect'],
      ['ideate-futures', '⟡', 'Futures'],
      ['ideate-competitive', '⚔', 'Competitive'],
      ['ideate-maturity', '▥', 'Maturity'],
      ['ideate-workshops', '☰', 'Workshops'],
      ['ideate-tentypes', '⑩', 'Ten Types'],
      ['ideate-funnel', '▼', 'Funnel'],
    ]],
    ['Decide', [
      ['command', '☑', 'Approvals'],
      ['campaigns', '📣', 'Campaigns'],
      ['pipeline', '≫', 'Pipeline'],
    ]],
    ['Value', [
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
          <h1>{collapsed ? <span className="accent">{workspace ? workspace.slice(0, 2).toUpperCase() : 'IH'}</span>
            : workspace ? <>{workspace}<span className="accent"> Hub</span></>
            : <>Innovation<span className="accent">Hub</span></>}</h1>
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
        <button className={authRequired ? "new-idea-cta" : "new-idea-cta cta-neutral"} onClick={() => setTab('ideas')}
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
        <a className="help-link nav-label" href="https://github.com/stocktradingclaw-creator/InnovationValueDashboard#readme"
           target="_blank" rel="noreferrer">Help &amp; docs ↗</a>
        {!authRequired && (
          <button className="new-idea-cta start-cta" onClick={() => setWantStart(true)}>
            <span className="nav-label">Start free</span>
            <span className="nav-glyph" aria-hidden="true">→</span>
          </button>
        )}
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
          <span className="row">
            <button className="new-idea-cta" style={{ width: 'auto' }}
                    onClick={() => setWantStart(true)}>Start free</button>
            <button className="chip"
                    onClick={() => window.dispatchEvent(new CustomEvent('ivd-nav', { detail: 'settings' }))}>
              or demo with my company's data
            </button>
            <button className="secondary" aria-label="Dismiss" onClick={() => {
              localStorage.setItem('ivd_seed_ack', '1'); refresh()
            }}>✕</button>
          </span>
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
        {tab === 'overview' && me && ideas.length === 0 && !hasData && (
          <div className="card">
            <h3>Welcome to {workspace ?? 'your workspace'} — first value in three steps</h3>
            {([
              ['Connect your data (or load samples) so the engine finds opportunities', 'sources', hasData],
              ['Submit your first idea — the AI drafts the description with you', 'ideas', ideas.length > 0],
              ['Add your team and their access levels', 'settings', false],
            ] as [string, Tab, boolean][]).map(([label, target, done], i) => (
              <div key={i} className="decision-row" role="button" tabIndex={0}
                   onKeyDown={(e) => { if (e.key === 'Enter') setTab(target) }}
                   onClick={() => setTab(target)}>
                <span className={`pill ${done ? 'act-approve' : 'act-verify'}`}>{done ? '✓' : i + 1}</span>
                <span>{label}</span>
              </div>
            ))}
          </div>
        )}
        {tab === 'overview' && <Dashboard data={dashboard} onNavigate={setTab} onChanged={refresh} />}
        {tab === 'ideas' && <Ideas ideas={ideas} onChanged={refresh} />}
        {tab === 'command' && <CommandCenter onChanged={refresh} />}
        {tab === 'campaigns' && <Campaigns ideas={ideas} onChanged={refresh} />}
        {tab === 'ideate-maturity' && <Maturity />}
        {tab !== 'ideate-maturity' && tab.startsWith('ideate-') && (
          <Ideate view={tab.slice(7) as import('./components/Ideate').IdeateView} onChanged={refresh} ideas={ideas} />
        )}
        {tab === 'pipeline' && <PipelineView />}
        {tab === 'settings' && <Settings onChanged={refresh} />}
        {tab === 'mine' && <MySubmissions me={me} />}
        {tab === 'sources' && <DataSources sources={sources} onChanged={refresh} />}
        {tab === 'opportunities' && (
          <Opportunities
            opportunities={opportunities}
            total={total}
            summary={summary}
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
