import { Link, NavLink, useNavigate } from 'react-router-dom';

export default function Header() {
  const nav = useNavigate();
  const token = localStorage.getItem('token');
  const logout = () => {
    localStorage.removeItem('token');
    nav('/');
  };

  return (
    <header className="site-header">
      <Link className="brand" to={token ? '/dashboard' : '/'} aria-label="Community Trust home">
        <span className="brand-mark" aria-hidden="true">CT</span>
        <span>Community Trust</span>
      </Link>
      <nav className="primary-nav" aria-label="Main navigation">
        {token ? (
          <>
            <NavLink to="/dashboard">Dashboard</NavLink>
            <NavLink to="/community">Community</NavLink>
            <button className="btn btn-secondary" onClick={logout}>Sign out</button>
          </>
        ) : (
          <Link className="btn btn-secondary" to="/login">Sign in</Link>
        )}
      </nav>
    </header>
  );
}   