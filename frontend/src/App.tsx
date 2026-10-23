import { useState } from 'react'
import { api, ApiError, getToken, setToken } from './api'
import { ItemView } from './components/ItemView'
import { JobList } from './components/JobList'
import { SearchView } from './components/SearchView'
import { usePoll } from './hooks'

type View = { kind: 'search' } | { kind: 'jobs' } | { kind: 'item'; ratingKey: string }

export default function App() {
  const [view, setView] = useState<View>({ kind: 'search' })
  const [tokenVersion, setTokenVersion] = useState(0)
  const presets = usePoll(() => api.presets(), 0, [tokenVersion])
  const jobs = usePoll(() => api.jobs(), 3000, [tokenVersion])
  const active = (jobs.data ?? []).filter((j) => j.status === 'queued' || j.status === 'running').length

  const unauthorized = presets.error instanceof ApiError && presets.error.status === 401
  if (unauthorized) {
    return <TokenPrompt onSaved={() => setTokenVersion((v) => v + 1)} />
  }

  const open = (ratingKey: string) => setView({ kind: 'item', ratingKey })

  return (
    <div className="app">
      <header className="topbar">
        <h1>Remastr</h1>
        <nav>
          <button className={view.kind !== 'jobs' ? 'tab active' : 'tab'} onClick={() => setView({ kind: 'search' })}>
            Mediathek
          </button>
          <button className={view.kind === 'jobs' ? 'tab active' : 'tab'} onClick={() => setView({ kind: 'jobs' })}>
            Jobs {active > 0 && <span className="count">{active}</span>}
          </button>
        </nav>
      </header>

      <main>
        {presets.error && !unauthorized && <p className="error">Backend nicht erreichbar: {presets.error.message}</p>}
        {/* Search stays mounted so results survive opening an item */}
        <div hidden={view.kind !== 'search'}>
          <SearchView presets={presets.data ?? []} onOpen={open} onQueued={() => setView({ kind: 'jobs' })} />
        </div>
        {view.kind === 'item' && (
          <ItemView ratingKey={view.ratingKey} presets={presets.data ?? []} onBack={() => setView({ kind: 'search' })} />
        )}
        {view.kind === 'jobs' && (
          <section>
            <h2>Jobs</h2>
            <JobList jobs={jobs.data ?? []} onOpen={open} onChange={() => void jobs.reload()} />
          </section>
        )}
      </main>
    </div>
  )
}

function TokenPrompt({ onSaved }: { onSaved: () => void }) {
  const [value, setValue] = useState(getToken())
  return (
    <div className="app">
      <form
        className="panel token"
        onSubmit={(e) => {
          e.preventDefault()
          setToken(value.trim())
          onSaved()
        }}
      >
        <h2>Remastr</h2>
        <p>Bitte den API-Token eingeben (REMASTR_API_TOKEN aus backend/.env).</p>
        <input type="password" value={value} onChange={(e) => setValue(e.target.value)} autoFocus aria-label="API-Token" />
        <button className="primary">Speichern</button>
      </form>
    </div>
  )
}
