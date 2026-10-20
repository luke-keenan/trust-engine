import Header from './Header';

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="app-shell">
      <Header />
      <main className="container app-main">
        {children}
      </main>
      <footer style={{
        padding: '16px 24px',
        borderTop: '1px solid var(--border)',
        textAlign: 'center',
        fontSize: 12,
        color: 'var(--text-dim)',
        }}>
      &copy; 2026 Community Trust. All rights reserved.
      </footer>   
    </div>
    
  );
}   
