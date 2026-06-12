import { useState } from 'react'
import { syncSap, syncServiceNow } from '../api'

interface Props {
  onChanged: () => void
}

function ServiceNowForm({ onChanged }: Props) {
  const [instanceUrl, setInstanceUrl] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [source, setSource] = useState<'cmdb' | 'itsm'>('cmdb')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sync = async () => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const res = await syncServiceNow({ instance_url: instanceUrl, username, password, source })
      setResult(`Synced ${res.rows_loaded} rows into ${res.source_type}.`)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>ServiceNow</h3>
        <span className="badge">Table API</span>
      </div>
      <p className="muted small">
        Pulls CIs (<code>cmdb_ci</code>) or tickets (<code>incident</code> +{' '}
        <code>sc_req_item</code>) over the REST Table API. Credentials are used for this sync
        only and never stored.
      </p>
      <div className="connector-form">
        <input
          placeholder="Instance URL — https://yourco.service-now.com"
          value={instanceUrl}
          onChange={(e) => setInstanceUrl(e.target.value)}
        />
        <div className="row">
          <input placeholder="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="row">
          <select value={source} onChange={(e) => setSource(e.target.value as 'cmdb' | 'itsm')}>
            <option value="cmdb">CMDB (configuration items)</option>
            <option value="itsm">ITSM (incidents + requests)</option>
          </select>
          <button disabled={busy || !instanceUrl || !username || !password} onClick={sync}>
            {busy ? 'Syncing…' : 'Sync'}
          </button>
        </div>
      </div>
      {result && <p className="success">{result}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

function SapForm({ onChanged }: Props) {
  const [serviceUrl, setServiceUrl] = useState('')
  const [entitySet, setEntitySet] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const sync = async () => {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const res = await syncSap({
        service_url: serviceUrl,
        entity_set: entitySet,
        username: username || undefined,
        password: password || undefined,
      })
      setResult(`Synced ${res.rows_loaded} invoice rows into ERP.`)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>SAP (OData)</h3>
        <span className="badge">OData v2/v4</span>
      </div>
      <p className="muted small">
        Pulls invoice line items from an SAP Gateway OData service into the ERP source. Field
        names map to common SAP invoice fields; pass a custom <code>field_map</code> via the API
        for non-standard services.
      </p>
      <div className="connector-form">
        <input
          placeholder="Service URL — https://host/sap/opu/odata/sap/ZINVOICE_SRV"
          value={serviceUrl}
          onChange={(e) => setServiceUrl(e.target.value)}
        />
        <div className="row">
          <input
            placeholder="Entity set — e.g. InvoiceSet"
            value={entitySet}
            onChange={(e) => setEntitySet(e.target.value)}
          />
        </div>
        <div className="row">
          <input placeholder="Username (optional)" value={username} onChange={(e) => setUsername(e.target.value)} />
          <input
            type="password"
            placeholder="Password (optional)"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <button disabled={busy || !serviceUrl || !entitySet} onClick={sync}>
            {busy ? 'Syncing…' : 'Sync'}
          </button>
        </div>
      </div>
      {result && <p className="success">{result}</p>}
      {error && <p className="error">{error}</p>}
    </div>
  )
}

export default function Connectors({ onChanged }: Props) {
  return (
    <>
      <h2 className="subsection">Live connectors</h2>
      <p className="muted">
        Pull directly from customer systems instead of CSV exports. Cloud billing stays
        CSV-based for now (use a Cost &amp; Usage Report export).
      </p>
      <div className="card-grid">
        <ServiceNowForm onChanged={onChanged} />
        <SapForm onChanged={onChanged} />
      </div>
    </>
  )
}
