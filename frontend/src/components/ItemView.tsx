import { useEffect, useRef, useState } from 'react'
import {
  api,
  DEFAULT_QUALITY,
  fileUrl,
  formatBytes,
  formatDuration,
  itemLabel,
  type Codec,
  type ItemDetail,
  type Job,
  type Preset,
  type PreviewRun,
} from '../api'
import { useAction, usePoll } from '../hooks'
import { Compare } from './Compare'
import { JobList } from './JobList'

type Props = { ratingKey: string; presets: Preset[]; onBack: () => void }

export function ItemView({ ratingKey, presets, onBack }: Props) {
  const detail = usePoll(() => api.item(ratingKey), 0, [ratingKey])
  const jobs = usePoll(() => api.jobs({ rating_key: ratingKey }), 2000, [ratingKey])

  // Refresh the local state whenever one of this item's jobs finishes
  const doneIds = (jobs.data ?? []).filter((j) => j.status === 'done').map((j) => j.id).join(',')
  const firstDone = useRef(true)
  useEffect(() => {
    if (firstDone.current) {
      firstDone.current = false
      return
    }
    void detail.reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doneIds])

  const queued = () => void jobs.reload()

  return (
    <section>
      <button className="link" onClick={onBack}>← Zurück zur Suche</button>
      {detail.error && <p className="error">{detail.error.message}</p>}
      {detail.data && (
        <>
          <Header detail={detail.data} />
          <SourcePanel detail={detail.data} jobs={jobs.data ?? []} onQueued={queued} />
          <PreviewPanel detail={detail.data} presets={presets} onQueued={queued} />
          <ProcessPanel detail={detail.data} presets={presets} onQueued={queued} />
          <OutputPanel detail={detail.data} onQueued={queued} />
        </>
      )}
      <div className="panel">
        <h3>Jobs für diesen Titel</h3>
        <JobList jobs={jobs.data ?? []} showTitle={false} onChange={queued} />
      </div>
    </section>
  )
}

function Header({ detail }: { detail: ItemDetail }) {
  const { item } = detail
  return (
    <header className="item-header">
      <h2>{itemLabel(item)}</h2>
      <dl className="facts">
        <div><dt>Bibliothek</dt><dd>{item.library}</dd></div>
        <div><dt>Auflösung</dt><dd className="mono">{item.width}×{item.height}</dd></div>
        <div><dt>Codec</dt><dd>{item.video_codec ?? '–'} / {item.container ?? '–'}</dd></div>
        <div><dt>Länge</dt><dd>{formatDuration(item.duration_s)}</dd></div>
        <div><dt>Größe</dt><dd>{formatBytes(item.size)}</dd></div>
      </dl>
      <p className="mono muted small-text break">{item.file}</p>
    </header>
  )
}

function SourcePanel({ detail, jobs, onQueued }: { detail: ItemDetail; jobs: Job[]; onQueued: () => void }) {
  const action = useAction()
  const downloading = jobs.some((j) => j.type === 'download' && (j.status === 'queued' || j.status === 'running'))
  return (
    <div className="panel">
      <h3>Original</h3>
      {detail.local.source ? (
        <p>Heruntergeladen: <span className="mono">{detail.local.source}</span></p>
      ) : downloading ? (
        <p className="muted">Download läuft…</p>
      ) : (
        <>
          <p className="muted">Noch nicht lokal vorhanden. Vorschau und Verarbeitung laden es bei Bedarf automatisch.</p>
          <button disabled={action.busy} onClick={() => void action.run(async () => (await api.download(detail.item.rating_key), onQueued()))}>
            Jetzt herunterladen
          </button>
        </>
      )}
      {action.error && <p className="error">{action.error}</p>}
    </div>
  )
}

const DEFAULT_PREVIEW = ['lanczos', 'scunet_vsr', 'dpir_vsr', 'esrgan']

function PreviewPanel({ detail, presets, onQueued }: { detail: ItemDetail; presets: Preset[]; onQueued: () => void }) {
  const [chosen, setChosen] = useState<Set<string>>(new Set(DEFAULT_PREVIEW.filter((id) => presets.some((p) => p.id === id))))
  const [start, setStart] = useState(120)
  const [length, setLength] = useState(30)
  const [runId, setRunId] = useState<string | null>(null)
  const action = useAction()
  const runs = detail.local.previews
  const run: PreviewRun | undefined = runs.find((r) => r.id === runId) ?? runs[0]

  const toggle = (id: string) =>
    setChosen((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  const create = () =>
    void action.run(async () => {
      await api.preview(detail.item.rating_key, [...chosen], start, length)
      onQueued()
    })

  return (
    <div className="panel">
      <h3>Testabschnitte</h3>
      <p className="muted">Derselbe Ausschnitt wird mit jedem gewählten Preset berechnet, danach direkt vergleichen.</p>
      <div className="preset-grid">
        {presets.map((p) => (
          <label key={p.id} className="preset" title={p.description}>
            <input type="checkbox" checked={chosen.has(p.id)} onChange={() => toggle(p.id)} />
            <span>
              <strong>{p.name}</strong>
              <span className="muted small-text">{p.description}</span>
            </span>
          </label>
        ))}
      </div>
      <div className="row wrap">
        <label>
          Start (s)
          <input type="number" min={0} value={start} onChange={(e) => setStart(Number(e.target.value))} />
        </label>
        <label>
          Länge (s)
          <input type="number" min={1} max={600} value={length} onChange={(e) => setLength(Number(e.target.value))} />
        </label>
        <button className="primary" disabled={action.busy || chosen.size === 0} onClick={create}>
          Vorschau erstellen
        </button>
      </div>
      {action.error && <p className="error">{action.error}</p>}

      {run && (
        <>
          {runs.length > 1 && (
            <label>
              Vorschau
              <select value={run.id} onChange={(e) => setRunId(e.target.value)}>
                {runs.map((r) => (
                  <option key={r.id} value={r.id}>
                    {new Date(r.created_at).toLocaleString()} · ab {r.start_s}s, {r.duration_s}s
                  </option>
                ))}
              </select>
            </label>
          )}
          {run.clips.length >= 2 ? (
            <Compare key={run.id} ratingKey={detail.item.rating_key} run={run} presets={presets} />
          ) : (
            <video controls src={fileUrl(detail.item.rating_key, run.clips[0].file)} className="single-video" />
          )}
        </>
      )}
    </div>
  )
}

function ProcessPanel({ detail, presets, onQueued }: { detail: ItemDetail; presets: Preset[]; onQueued: () => void }) {
  const [chosenPreset, setPreset] = useState<string>()
  const preset = chosenPreset ?? presets[0]?.id ?? ''
  const [codec, setCodec] = useState<Codec>('hevc')
  const [quality, setQuality] = useState(DEFAULT_QUALITY)
  const action = useAction()
  return (
    <div className="panel">
      <h3>Komplett verarbeiten</h3>
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
        <label title="QVBR: kleiner = bessere Qualität, größere Datei">
          Qualität
          <input type="number" min={1} max={51} value={quality} onChange={(e) => setQuality(Number(e.target.value))} />
        </label>
        <button
          className="primary"
          disabled={action.busy}
          onClick={() =>
            void action.run(async () => (await api.process(detail.item.rating_key, { preset, codec, quality }), onQueued()))
          }
        >
          Verarbeitung starten
        </button>
      </div>
      {action.error && <p className="error">{action.error}</p>}
    </div>
  )
}

function OutputPanel({ detail, onQueued }: { detail: ItemDetail; onQueued: () => void }) {
  const [armReplace, setArmReplace] = useState(false)
  const action = useAction()
  const rk = detail.item.rating_key
  if (detail.local.outputs.length === 0) return null

  const upload = (mode: 'version' | 'replace') =>
    void action.run(async () => {
      await api.upload(rk, { mode, confirm: mode === 'replace' })
      setArmReplace(false)
      onQueued()
    })

  return (
    <div className="panel">
      <h3>Ergebnis</h3>
      <ul className="plain outputs">
        {detail.local.outputs.map((o) => (
          <li key={o.file}>
            <a href={fileUrl(rk, o.file)} target="_blank" rel="noreferrer" className="mono">{o.file.split('/').pop()}</a>
            <div className="output-meta">
              <strong>{o.preset_name ?? 'Preset unbekannt'}</strong>
              {o.codec && <span>{o.codec.toUpperCase()} · Qualität {o.quality}</span>}
              <span>{formatBytes(o.size)}</span>
              {o.created_at && <span>{new Date(o.created_at).toLocaleString()}</span>}
            </div>
            {o.description && <div className="muted small-text">{o.description}</div>}
          </li>
        ))}
      </ul>
      <div className="row wrap">
        <button className="primary" disabled={action.busy} onClick={() => upload('version')}>
          Als zusätzliche Version hochladen
        </button>
        {!armReplace ? (
          <button className="danger-outline" disabled={action.busy} onClick={() => setArmReplace(true)}>
            Original ersetzen…
          </button>
        ) : (
          <span className="warn-box">
            Das Original wird in den Archiv-Ordner verschoben.
            <button className="danger" disabled={action.busy} onClick={() => upload('replace')}>Ja, ersetzen</button>
            <button onClick={() => setArmReplace(false)}>Abbrechen</button>
          </span>
        )}
      </div>
      {action.error && <p className="error">{action.error}</p>}
    </div>
  )
}
