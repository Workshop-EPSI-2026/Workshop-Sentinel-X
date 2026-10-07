import { useState, type FormEvent } from 'react';

export function Login({ error, onToken, onDemo }: { error: string | null; onToken: (token: string) => void; onDemo: () => void }) {
  const [token, setToken] = useState('');

  function submit(e: FormEvent) {
    e.preventDefault();
    if (token.trim()) onToken(token.trim());
  }

  return (
    <main className="login">
      <form className="card login-card" onSubmit={submit}>
        <h1>Sentinel-X</h1>
        <p className="muted">Supervision AetherCorp · accès opérateur</p>
        <label className="field">
          <span className="field-label">Jeton opérateur</span>
          <input type="password" value={token} onChange={(e) => setToken(e.target.value)} autoComplete="current-password" autoFocus />
        </label>
        {error && <p className="error small" role="alert">{error}</p>}
        <button type="submit" className="btn primary" disabled={!token.trim()}>Se connecter</button>
        <div className="login-sep"><span>ou</span></div>
        <button type="button" className="btn" onClick={onDemo}>Mode démo (sans API)</button>
        <p className="muted small">Le mode démo simule le boîtier, Sentinel Brain et les incidents, avec des scénarios à déclencher.</p>
      </form>
    </main>
  );
}
