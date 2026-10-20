import { useCallback, useEffect, useState, type FormEvent } from 'react';
import axios from 'axios';
import api from '../api';
import type { Collab } from '../types';

const FOCI = ['research', 'policy', 'industry', 'academic', 'general'] as const;
type Focus = (typeof FOCI)[number];

function isCollab(value: unknown): value is Collab {
  if (typeof value !== 'object' || value === null) return false;

  const collab = value as Record<string, unknown>;
  return (
    typeof collab.id === 'string' &&
    typeof collab.name === 'string' &&
    typeof collab.focus === 'string' &&
    typeof collab.member_count === 'number' &&
    Number.isFinite(collab.member_count) &&
    (collab.status === 'active' || collab.status === 'community')
  );
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return fallback;
}

export default function Community() {
  const [collabs, setCollabs] = useState<Collab[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [createError, setCreateError] = useState('');
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [focus, setFocus] = useState<Focus>('research');

  const fetchCollabs = useCallback(async () => {
    const { data } = await api.get<unknown>('/collabs');
    if (!Array.isArray(data) || !data.every(isCollab)) {
      throw new Error('The server returned an invalid collaboration list.');
    }
    return data;
  }, []);

  useEffect(() => {
    let active = true;
    fetchCollabs()
      .then((data) => {
        if (active) setCollabs(data);
      })
      .catch((error: unknown) => {
        if (active) setLoadError(getErrorMessage(error, 'Failed to load collaborations.'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [fetchCollabs]);

  const loadCollabs = async () => {
    setLoading(true);
    setLoadError('');
    try {
      setCollabs(await fetchCollabs());
    } catch (error: unknown) {
      setLoadError(getErrorMessage(error, 'Failed to load collaborations.'));
    } finally {
      setLoading(false);
    }
  };

  const create = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedName = name.trim();
    if (!trimmedName || creating) return;

    setCreating(true);
    setCreateError('');
    try {
      const { data } = await api.post<unknown>('/collabs', {
        name: trimmedName,
        focus,
      });
      if (!isCollab(data)) {
        throw new Error('The server returned an invalid collaboration.');
      }
      setCollabs((current) => [data, ...current]);
      setName('');
    } catch (error: unknown) {
      setCreateError(getErrorMessage(error, 'Failed to create collaboration.'));
    } finally {
      setCreating(false);
    }
  };

  return (
    <div>
      <div className="page-heading">
        <h2>Communities</h2>
        <p>Connect with people building more trustworthy AI systems.</p>
      </div>

      {loadError && (
        <div>
          <p className="notice-error" role="alert">{loadError}</p>
          <button type="button" className="btn btn-secondary" onClick={() => void loadCollabs()} disabled={loading}>
            {loading ? 'Retrying…' : 'Retry loading'}
          </button>
        </div>
      )}
      {createError && (
        <p className="notice-error" role="alert">{createError}</p>
      )}

      <form onSubmit={create} className="card community-form">
        <input
          className="input"
          aria-label="Community name"
          placeholder="Community name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <label className="community-focus">
          Focus
          <select
            className="input"
            value={focus}
            onChange={(event) => {
              const selected = FOCI.find((item) => item === event.target.value);
              if (selected) setFocus(selected);
            }}
          >
            {FOCI.map((item) => (
              <option key={item} value={item}>{item}</option>
            ))}
          </select>
        </label>
        <button type="submit" className="btn btn-primary" disabled={loading || creating || !name.trim()}>
          {creating ? 'Creating…' : 'Create community'}
        </button>
      </form>

      {loading && (
        <div className="loading-state" role="status" aria-live="polite">
          Loading communities…
        </div>
      )}

      {!loading && !loadError && collabs.length === 0 && (
        <div className="empty-state">
          <h3>No communities yet</h3>
          <p>Create a community to start connecting with other members.</p>
        </div>
      )}

      <div className="community-grid">
        {collabs.map((collab) => (
          <article key={collab.id} className="card community-card">
            <h3>{collab.name}</h3>
            <p style={{ color: 'var(--text-dim)', fontSize: 13 }}>{collab.focus}</p>
            <div style={{ marginTop: 12, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span className="badge badge-pass">{collab.member_count} members</span>
              <span style={{ fontSize: 12, color: 'var(--text-dim)' }}>{collab.status}</span>
            </div>
          </article>
        ))}
      </div>
    </div>
  );
}
