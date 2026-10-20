import { LineChart, Line, XAxis, YAxis, CartesianGrid, ResponsiveContainer, ReferenceLine } from 'recharts';
import type { ChartPoint } from '../types';

export default function ScoreChart({ points }: { points: ChartPoint[] }) {
  return (
    <div className="card">
      <h3 style={{ marginBottom: 16 }}>Trust Score History</h3>
      <ResponsiveContainer width="100%" height={250}>
        <LineChart data={points}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
          <XAxis dataKey="timestamp" stroke="var(--text-dim)" fontSize={11} />
          <YAxis domain={[0, 1000]} stroke="var(--text-dim)" fontSize={11} />
          <ReferenceLine y={700} stroke="var(--accent)" strokeDasharray="4 4" label={{ value: 'Trust', fill: 'var(--accent)', fontSize: 11 }} />
          <ReferenceLine y={400} stroke="var(--warn)" strokeDasharray="4 4" label={{ value: 'Warn', fill: 'var(--warn)', fontSize: 11 }} />
          <Line type="monotone" dataKey="trust_score" stroke="var(--accent-2)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}   