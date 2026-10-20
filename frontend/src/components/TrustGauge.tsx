interface Props { score: number; trusted: boolean; }

export default function TrustGauge({ score, trusted }: Props) {
  const color = trusted ? 'var(--accent)' : score >= 400 ? 'var(--warn)' : 'var(--danger)';
  return (
    <div style={{ textAlign: 'center' }}>
      <div style={{
        width: 120, height: 120, borderRadius: '50%',
        border: `6px solid ${color}`,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        margin: '0 auto 12px',
        position: 'relative',
      }}>
        <span style={{ fontSize: 32, fontWeight: 700, color }}>{score}</span>
        <span style={{ position: 'absolute', bottom: 16, fontSize: 11, color: 'var(--text-dim)' }}>/1000</span>
      </div>
      <span className={`badge ${trusted ? 'badge-pass' : 'badge-fail'}`}>
        {trusted ? 'TRUSTED' : 'UNTRUSTED'}
      </span>
    </div>
  );
}   