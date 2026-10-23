import { useEffect, useRef, useState } from 'react'
import { fileUrl, type Preset, type PreviewRun } from '../api'

type Props = { ratingKey: string; run: PreviewRun; presets: Preset[] }

const FRAME = 1 / 25

/** Two preview clips on top of each other; a draggable divider reveals the left clip. Playback stays in sync. */
export function Compare({ ratingKey, run, presets }: Props) {
  const ids = run.clips.map((c) => c.preset)
  const [left, setLeft] = useState(ids.includes('lanczos') ? 'lanczos' : ids[0])
  const [right, setRight] = useState(ids.find((id) => id !== 'lanczos' && id !== left) ?? ids[ids.length - 1])
  const [split, setSplit] = useState(50)
  const [playing, setPlaying] = useState(false)
  const [time, setTime] = useState(0)
  const [duration, setDuration] = useState(run.duration_s)
  const leftRef = useRef<HTMLVideoElement>(null)
  const rightRef = useRef<HTMLVideoElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)

  const name = (id: string) => presets.find((p) => p.id === id)?.name ?? id
  const src = (id: string) => fileUrl(ratingKey, run.clips.find((c) => c.preset === id)!.file)

  // Keep the left (overlay) video locked to the right (master) video
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const a = leftRef.current
      const b = rightRef.current
      if (a && b) {
        if (Math.abs(a.currentTime - b.currentTime) > 0.04) a.currentTime = b.currentTime
        const t = b.currentTime
        setTime((prev) => (Math.abs(prev - t) > 0.04 ? t : prev)) // unchanged value = no re-render
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [])

  // Switching clips: keep position and play state
  useEffect(() => {
    const b = rightRef.current
    const a = leftRef.current
    if (!a || !b) return
    a.currentTime = b.currentTime
    if (playing) void Promise.all([a.play(), b.play()]).catch(() => setPlaying(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [left, right])

  const both = (fn: (v: HTMLVideoElement) => void) => {
    for (const v of [leftRef.current, rightRef.current]) if (v) fn(v)
  }

  const toggle = () => {
    if (playing) {
      both((v) => v.pause())
      setPlaying(false)
    } else {
      both((v) => void v.play())
      setPlaying(true)
    }
  }

  const seek = (t: number) => {
    const clamped = Math.max(0, Math.min(t, duration))
    both((v) => (v.currentTime = clamped))
    setTime(clamped)
  }

  const step = (frames: number) => {
    both((v) => v.pause())
    setPlaying(false)
    seek((rightRef.current?.currentTime ?? 0) + frames * FRAME)
  }

  const moveDivider = (clientX: number) => {
    const rect = stageRef.current?.getBoundingClientRect()
    if (rect) setSplit(Math.max(0, Math.min(100, ((clientX - rect.left) / rect.width) * 100)))
  }

  return (
    <div className="compare">
      <div className="compare-pickers">
        <label>
          Links
          <select value={left} onChange={(e) => setLeft(e.target.value)}>
            {ids.map((id) => (
              <option key={id} value={id}>{name(id)}</option>
            ))}
          </select>
        </label>
        <label>
          Rechts
          <select value={right} onChange={(e) => setRight(e.target.value)}>
            {ids.map((id) => (
              <option key={id} value={id}>{name(id)}</option>
            ))}
          </select>
        </label>
      </div>

      <div
        ref={stageRef}
        className="compare-stage"
        onPointerDown={(e) => {
          dragging.current = true
          e.currentTarget.setPointerCapture(e.pointerId)
          moveDivider(e.clientX)
        }}
        onPointerMove={(e) => dragging.current && moveDivider(e.clientX)}
        onPointerUp={() => (dragging.current = false)}
      >
        <video
          ref={rightRef}
          src={src(right)}
          muted
          loop
          playsInline
          preload="auto"
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
        />
        <video
          ref={leftRef}
          src={src(left)}
          muted
          loop
          playsInline
          preload="auto"
          className="compare-overlay"
          style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
        />
        <div className="compare-divider" style={{ left: `${split}%` }} />
        <span className="compare-tag compare-tag-left">{name(left)}</span>
        <span className="compare-tag compare-tag-right">{name(right)}</span>
      </div>

      <div className="compare-controls">
        <button onClick={() => step(-1)} title="Ein Bild zurück">◀︎|</button>
        <button onClick={toggle} className="primary">{playing ? 'Pause' : 'Abspielen'}</button>
        <button onClick={() => step(1)} title="Ein Bild vor">|▶︎</button>
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={FRAME}
          value={time}
          onChange={(e) => seek(Number(e.target.value))}
          aria-label="Position"
        />
        <span className="mono">{time.toFixed(2)} s</span>
      </div>
    </div>
  )
}
