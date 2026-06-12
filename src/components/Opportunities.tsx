import { useState } from 'react'
import { money } from '../api'
import type { Opportunity } from '../types'

interface Props {
  opportunities: Opportunity[]
  total: number
  hasData: boolean
}

const SOURCE_LABELS: Record<string, string> = {
  cmdb: 'CMDB',
  erp: 'ERP',
  cloud: 'Cloud',
  itsm: 'ITSM',
}

export default function Opportunities({ opportunities, total, hasData }: Props) {
  const [sourceFilter, setSourceFilter] = useState<string>('all')
  const [expanded, setExpanded] = useState<string | null>(null)

  if (!hasData) {
    return (
      <section>
        <h2>Cost-reduction opportunities</h2>
        <p className="muted">
          No data loaded yet. Go to <strong>Data Sources</strong> and upload customer exports or
          load the sample data.
        </p>
      </section>
    )
  }

  const filtered =
    sourceFilter === 'all'
      ? opportunities
      : opportunities.filter((o) => o.source === sourceFilter)

  return (
    <section>
      <div className="section-header">
        <div>
          <h2>Cost-reduction opportunities</h2>
          <p className="muted">
            {opportunities.length} opportunities identified across the loaded sources.
          </p>
        </div>
        <div className="total-banner">
          <span className="muted">Total identified</span>
          <strong>{money(total)}/yr</strong>
        </div>
      </div>

      <div className="row filter-row">
        {['all', 'cmdb', 'erp', 'cloud', 'itsm'].map((s) => (
          <button
            key={s}
            className={sourceFilter === s ? 'chip chip-active' : 'chip'}
            onClick={() => setSourceFilter(s)}
          >
            {s === 'all' ? 'All sources' : SOURCE_LABELS[s]}
          </button>
        ))}
      </div>

      <table className="opps-table">
        <thead>
          <tr>
            <th>Source</th>
            <th>Opportunity</th>
            <th className="num">Est. annual savings</th>
            <th>Effort</th>
            <th>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {filtered.map((o) => (
            <>
              <tr
                key={o.id}
                className="opp-row"
                onClick={() => setExpanded(expanded === o.id ? null : o.id)}
              >
                <td>
                  <span className={`tag tag-${o.source}`}>{SOURCE_LABELS[o.source]}</span>
                </td>
                <td>
                  <strong>{o.title}</strong>
                  <div className="muted small">{o.category}</div>
                </td>
                <td className="num savings">{money(o.estimated_annual_savings)}</td>
                <td>
                  <span className={`pill pill-${o.effort}`}>{o.effort}</span>
                </td>
                <td>
                  <span className={`pill pill-${o.confidence}`}>{o.confidence}</span>
                </td>
              </tr>
              {expanded === o.id && (
                <tr key={`${o.id}-detail`} className="detail-row">
                  <td colSpan={5}>
                    <p>{o.description}</p>
                    <p className="muted small">
                      Affected ({o.affected_count}): {o.affected_items.join(', ')}
                      {o.affected_count > o.affected_items.length && ' …'}
                    </p>
                  </td>
                </tr>
              )}
            </>
          ))}
        </tbody>
      </table>
    </section>
  )
}
