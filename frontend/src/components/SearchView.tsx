import { type FormEvent, useState } from 'react'
import { api, DEFAULT_QUALITY, formatBytes, formatDuration, itemLabel, type Codec, type PlexItem, type Preset, type UploadMode } from '../api'
import { useAction, usePoll } from '../hooks'

type Props = { presets: Preset[]; onOpen: (ratingKey: string) => void; onQueued: () => void }

export function SearchView({ presets, onOpen, onQueued }: Props) {
  const libraries = usePoll(() => api.libraries(), 0, [])
  const [query, setQuery] = useState('')
  const [library, setLibrary] = useState('')
  const [results, setResults] = useState<PlexItem[] | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const search = useAction()

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    const items = await search.run(() => api.search(query.trim(), library || undefined))
    if (items) {
      setResults(items)
      setSelected(new Set())
    }
  }

  const toggle = (rk: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(rk)) next.delete(rk)
      else next.add(rk)
      return next
    })

  return (
    <section>
      <form className="row" onSubmit={submit}>
        <input
          type="search"
          placeholder="Film, Serie oder Folge suchen…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          autoFocus
        />
        <select value={library} onChange={(e) => setLibrary(e.target.value)} aria-label="Bibliothek">
          <option value="">Alle Bibliotheken</option>
          {libraries.data?.map((l) => (
            <option key={l.key} value={l.key}>{l.title}</option>
          ))}
        </select>
        <button className="primary" disabled={search.busy}>Suchen</button>
      </form>
      {libraries.error && <p className="error">Plex: {libraries.error.message}</p>}
      {search.error && <p className="error">{search.error}</p>}

      {results && (
        <>
          <p className="muted">{results.length} Treffer</p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      aria-label="Alle auswählen"
                      checked={results.length > 0 && selected.size === results.length}
                      onChange={(e) =>
                        setSelected(e.target.checked ? new Set(results.map((r) => r.rating_key)) : new Set())
                      }
                    />
                  </th>
                  <th>Titel</th>
                  <th>Auflösung</th>
                  <th>Länge</th>
                  <th>Größe</th>
                </tr>
              </thead>
              <tbody>
                {results.map((item) => (
                  <tr key={item.rating_key}>
                    <td>
                      <input
                        type="checkbox"
                        aria-label="Auswählen"
                        checked={selected.has(item.rating_key)}
                        onChange={() => toggle(item.rating_key)}
                      />
                    </td>
                    <td>
                      <button className="link" onClick={() => onOpen(item.rating_key)}>{itemLabel(item)}</button>
                      <div className="muted small-text">{item.library}</div>
                    </td>
                    <td className="mono">{item.width && item.height ? `${item.width}×${item.height}` : '–'}</td>
                    <td>{formatDuration(item.duration_s)}</td>
                    <td>{formatBytes(item.size)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {selected.size > 0 && (
        <BatchPanel presets={presets} ratingKeys={[...selected]} onQueued={onQueued} />
      )}
    </section>
  )
}

function BatchPanel({ presets, ratingKeys, onQueued }: { presets: Preset[]; ratingKeys: string[]; onQueued: () => void }) {
  const [chosenPreset, setPreset] = useState<string>()
  const preset = chosenPreset ?? presets[0]?.id ?? ''
  const [codec, setCodec] = useState<Codec>('hevc')
  const [quality, setQuality] = useState(DEFAULT_QUALITY)
  const [upload, setUpload] = useState<'none' | UploadMode>('none')
  const [confirmReplace, setConfirmReplace] = useState(false)
  const action = useAction()

  const start = async () => {
    const jobs = await action.run(() =>
      api.batch(
        ratingKeys,
        { preset, codec, quality },
        upload === 'none' ? null : { mode: upload, confirm: confirmReplace },
      ),
    )
    if (jobs) onQueued()
  }

  return (
    <div className="panel batch">
      <h3>Batch: {ratingKeys.length} ausgewählt</h3>
      <div className="row wrap">
        <label>
          Preset
          <select value={preset} onChange={(e) => setPreset(e.target.value)}>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        </label>
        <label>
          Codec
          <select value={codec} onChange={(e) => setCodec(e.target.value as Codec)}>
            <option value="hevc">HEVC</option>
            <option value="av1">AV1</option>
          </select>
        </label>
        <label>
          Qualität
          <input type="number" min={1} max={51} value={quality} onChange={(e) => setQuality(Number(e.target.value))} />
        </label>
        <label>
          Danach
          <select value={upload} onChange={(e) => setUpload(e.target.value as 'none' | UploadMode)}>
            <option value="none">nicht hochladen</option>
            <option value="version">als zusätzliche Version hochladen</option>
            <option value="replace">Original ersetzen</option>
          </select>
        </label>
      </div>
      {upload === 'replace' && (
        <label className="warn-box">
          <input type="checkbox" checked={confirmReplace} onChange={(e) => setConfirmReplace(e.target.checked)} />
          Originale werden in den Archiv-Ordner verschoben und durch die verbesserte Datei ersetzt.
        </label>
      )}
      {action.error && <p className="error">{action.error}</p>}
      <button
        className="primary"
        disabled={action.busy || (upload === 'replace' && !confirmReplace)}
        onClick={() => void start()}
      >
        Batch starten
      </button>
    </div>
  )
}
