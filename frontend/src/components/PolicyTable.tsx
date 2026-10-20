import type { PolicyResult } from '../types';

export default function PolicyTable({ results }: { results: PolicyResult[] }) {
  return (
    <div className="card" style={{ overflowX: 'auto' }}>
      <h3 style={{ marginBottom: 16 }}>Policy Compliance</h3>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
            <th style={{ padding: '8px 12px' }}>Rule</th>
            <th style={{ padding: '8px 12px' }}>Sutra</th>
            <th style={{ padding: '8px 12px' }}>Result</th>
          </tr>
        </thead>
        <tbody>
          {results.map((r) => (
            <tr key={r.rule_id} style={{ borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '8px 12px' }}>{r.rule_name}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-dim)', fontSize: 12 }}>{r.sutra}</td>
              <td style={{ padding: '8px 12px' }}>
                <span className={`badge badge-${r.result}`}>{r.result.toUpperCase()}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}   