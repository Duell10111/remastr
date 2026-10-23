import { api, type Job } from '../api'
import { useAction } from '../hooks'

const TYPE_LABEL: Record<Job['type'], string> = {
  download: 'Download',
  preview: 'Vorschau',
  process: 'Verarbeitung',
  upload: 'Upload',
}

const STATUS_LABEL: Record<Job['status'], string> = {
  queued: 'wartet',
  running: 'läuft',
  done: 'fertig',
  failed: 'Fehler',
  cancelled: 'abgebrochen',
}

type Props = { jobs: Job[]; showTitle?: boolean; onOpen?: (ratingKey: string) => void; onChange?: () => void }

export function JobList({ jobs, showTitle = true, onOpen, onChange }: Props) {
  const { run, error } = useAction()
  if (jobs.length === 0) return <p className="muted">Keine Jobs.</p>

  return (
    <>
      {error && <p className="error">{error}</p>}
      <ul className="jobs">
        {jobs.map((job) => (
          <li key={job.id} className={`job job-${job.status}`}>
            <div className="job-head">
              <span className="mono muted">#{job.id}</span>
              <strong>{TYPE_LABEL[job.type]}</strong>
              {showTitle &&
                (onOpen ? (
                  <button className="link" onClick={() => onOpen(job.rating_key)}>{job.title}</button>
                ) : (
                  <span>{job.title}</span>
                ))}
              <span className={`badge badge-${job.status}`}>{STATUS_LABEL[job.status]}</span>
              {job.depends_on && job.status === 'queued' && <span className="muted">nach #{job.depends_on}</span>}
              {(job.status === 'queued' || job.status === 'running') && (
                <button
                  className="small"
                  onClick={() => void run(async () => (await api.cancel(job.id), onChange?.()))}
                >
                  Abbrechen
                </button>
              )}
            </div>
            {job.status === 'running' && (
              <progress max={1} value={job.progress} aria-label="Fortschritt" />
            )}
            {job.message && <div className="job-message">{job.message}</div>}
          </li>
        ))}
      </ul>
    </>
  )
}
