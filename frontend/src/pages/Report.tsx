import { useParams, Link } from 'react-router-dom';
import { useEffect, useState } from 'react';
import api from '../api';

export default function Report() {
  const { id } = useParams();
  const [data, setData] = useState<any>(null);

  useEffect(() => {
    if (id) api.get(`/trust/${id}`).then((r) => setData(r.data)).catch(() => {});
  }, [id]);

  if (!data) return <p>Loading…</p>;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 24 }}>
        <h2>Compliance Report — {data.system_id}</h2>
        <Link to="/dashboard"><button className="btn btn-secondary">← Back</button></Link>
      </div>
      <div className="card">
        <p style={{ color: 'var(--text-dim)' }}>
          {data.evaluations?.length ?? 0} evaluations on record.
        </p>
        {data.evaluations?.[0] && (
          <table style={{ width: '100%', marginTop: 16 }}>
            <tbody>
              {data.evaluations.slice(0, 5).map((ev: any) => (
                <tr key={ev.id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '8px 0' }}>{new Date(ev.timestamp).toLocaleString()}</td>
                  <td style={{ padding: '8px 0' }}>{ev.trust_score}</td>
                  <td style={{ padding: '8px 0' }}>
                    <span className={`badge ${ev.trusted ? 'badge-pass' : 'badge-fail'}`}>
                      {ev.trusted ? 'TRUSTED' : 'UNTRUSTED'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}   