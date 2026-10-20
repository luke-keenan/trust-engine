import { useState, type FormEvent } from 'react';
import axios from 'axios';
import api from '../api';
import TrustGauge from '../components/TrustGauge';
import PolicyTable from '../components/PolicyTable';
import ScoreChart from '../components/ScoreChart';
import type { Evaluation, ChartPoint } from '../types';

const DEFAULT_SIGNALS = {
  model_drift: 0.05, data_quality: 0.95,
  access_anomaly_count: 0, output_variance: 0.1,
  fairness_metric: 0.95, human_oversight: true,
  bias_audit_done: true, data_lineage_documented: true,
};

export default function Dashboard() {
  const [systemId, setSystemId] = useState('');
  const [result, setResult] = useState<Evaluation | null>(null);
  const [chart, setChart] = useState<ChartPoint[]>([]);
  const [chartError, setChartError] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const evaluate = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const normalizedId = systemId.trim();
    if (!normalizedId || loading) return;
    setLoading(true);
    setError('');
    setChartError('');
    setResult(null);
    setChart([]);
    try {
      const { data } = await api.post('/evaluate', { system_id: normalizedId, signals: DEFAULT_SIGNALS });
      setResult(data);
      try {
        const chartRes = await api.get(`/chart/${encodeURIComponent(normalizedId)}`);
        setChart(chartRes.data.points);
      } catch (err: unknown) {
        const message = axios.isAxiosError(err)
          ? err.response?.data?.detail
          : undefined;
        setChartError(
          typeof message === 'string'
            ? `Evaluation completed, but score history could not be loaded: ${message}`
            : 'Evaluation completed, but score history could not be loaded.',
        );
      }
    } catch (err: any) {
      const message = axios.isAxiosError(err)
        ? err.response?.data?.detail
        : undefined;
      setError(typeof message === 'string' ? message : 'Evaluation failed. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <div className="page-heading">
        <h2>System evaluation</h2>
        <p>Run a policy and risk assessment for an AI system.</p>
      </div>

      <form onSubmit={evaluate} className="card dashboard-form">
        <input
          className="input"
          aria-label="System ID"
          placeholder="System ID (e.g. my-ai-service)"
          value={systemId}
          onChange={(e) => setSystemId(e.target.value)}
          required
        />
        <button type="submit" className="btn btn-primary" disabled={loading || !systemId.trim()}>
          {loading ? 'Evaluating…' : 'Run evaluation'}
        </button>
      </form>

      {error && <p className="notice-error" role="alert">{error}</p>}
      {chartError && <p className="notice-info" role="status">{chartError}</p>}

      {loading && (
        <div className="loading-state" role="status" aria-live="polite">
          Evaluating system…
        </div>
      )}

      {result && (
        <section className="evaluation-grid" aria-label="Evaluation results">
          <div className="card evaluation-summary">
            <TrustGauge score={result.trust_score} trusted={result.trusted} />
            <p>
              Risk: {result.risk_tier} · Uncertainty: {(result.uncertainty * 100).toFixed(1)}%
            </p>
          </div>
          <div className="evaluation-details">
            <PolicyTable results={result.policy_results} />
            {chart.length > 0 && (
              <ScoreChart points={chart} />
            )}
          </div>
        </section>
      )}
    </div>
  );
}   