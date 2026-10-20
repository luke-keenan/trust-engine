import { Link } from 'react-router-dom';

export default function Landing() {
  return (
    <div className="landing">
      <header className="landing-header">
        <Link className="brand" to="/" aria-label="Community Trust home">
          <span className="brand-mark" aria-hidden="true">CT</span>
          <span>Community Trust</span>
        </Link>
        <nav className="primary-nav" aria-label="Main navigation">
          <Link className="btn btn-secondary" to="/login">Sign in</Link>
          <Link className="btn btn-primary" to="/login?mode=register">Create account</Link>
        </nav>
      </header>

      <main>
        <section className="landing-hero">
          <span className="eyebrow">Trustworthy AI starts with evidence</span>
          <h1>
            Governance you can
            <br />
            <span>measure and trust.</span>
          </h1>
          <p>
            Evaluate AI systems against India AI Sutra and NIST AI RMF.
            Bring risk scoring, policy checks, and community governance together.
          </p>
          <div className="landing-actions">
            <Link className="btn btn-primary" to="/login?mode=register">Get started</Link>
            <a className="btn btn-secondary" href="#features">Explore the platform</a>
          </div>
        </section>

        <section className="container feature-grid" id="features" aria-label="Platform features">
          {[
            { title: 'Policy engine', desc: 'Seven clear checks map your system to India AI Sutra and NIST AI RMF.' },
            { title: 'Risk assessment', desc: 'Ensemble scoring provides a consistent view of system risk and uncertainty.' },
            { title: 'Community governance', desc: 'Build accountable communities with member participation and shared trust.' },
          ].map((feature) => (
            <article key={feature.title} className="card feature-card">
              <h3>{feature.title}</h3>
              <p>{feature.desc}</p>
            </article>
          ))}
        </section>
        <footer style={{
            padding: '24px',
            borderTop: '1px solid var(--border)',
            textAlign: 'center',
            fontSize: 13,
            color: 'var(--text-dim)',   
          }}>
        &copy; 2026 Community Trust Engine. Built for responsible AI governance in India.
        </footer>   
      </main>
    </div>
  );
}