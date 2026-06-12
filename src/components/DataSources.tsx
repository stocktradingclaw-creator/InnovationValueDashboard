import { useRef, useState } from 'react'
import { clearDataset, loadSamples, uploadDataset } from '../api'
import type { SourceStatus } from '../types'
import Connectors from './Connectors'

interface Props {
  sources: SourceStatus[]
  onChanged: () => void
}

function SourceCard({ source, onChanged }: { source: SourceStatus; onChanged: () => void }) {
  const fileInput = useRef<HTMLInputElement>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const handleFile = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      await uploadDataset(source.source_type, file)
      onChanged()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  return (
    <div className="card">
      <div className="card-header">
        <h3>{source.label}</h3>
        <span className={source.rows_loaded > 0 ? 'badge badge-ok' : 'badge'}>
          {source.rows_loaded > 0
            ? `${source.rows_loaded} rows${source.origin ? ` · ${source.origin}` : ''}`
            : 'no data'}
        </span>
      </div>
      <p className="muted">
        Required columns: <code>{source.required_columns.join(', ')}</code>
      </p>
      <div className="row">
        <input
          ref={fileInput}
          type="file"
          accept=".csv"
          style={{ display: 'none' }}
          onChange={(e) => e.target.files?.[0] && handleFile(e.target.files[0])}
        />
        <button disabled={busy} onClick={() => fileInput.current?.click()}>
          {busy ? 'Uploading…' : 'Upload CSV'}
        </button>
        {source.rows_loaded > 0 && (
          <button
            className="secondary"
            onClick={async () => {
              await clearDataset(source.source_type)
              onChanged()
            }}
          >
            Clear
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </div>
  )
}

export default function DataSources({ sources, onChanged }: Props) {
  const [busy, setBusy] = useState(false)
  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Customer data sources</h2>
          <p className="muted">
            Connect exports from the customer's estate. The opportunity engine analyzes whatever
            is loaded.
          </p>
        </div>
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true)
            try {
              await loadSamples()
              onChanged()
            } finally {
              setBusy(false)
            }
          }}
        >
          {busy ? 'Loading…' : 'Load sample data'}
        </button>
      </div>
      <div className="card-grid">
        {sources.map((s) => (
          <SourceCard key={s.source_type} source={s} onChanged={onChanged} />
        ))}
      </div>
      <Connectors onChanged={onChanged} />
    </section>
  )
}
