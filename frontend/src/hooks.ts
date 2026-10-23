import { useCallback, useEffect, useRef, useState } from 'react'

/** Loads data once and then every intervalMs (0 = no polling). Reloads when deps change. */
export function usePoll<T>(load: () => Promise<T>, intervalMs: number, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const loadRef = useRef(load)
  loadRef.current = load

  const reload = useCallback(async () => {
    try {
      setData(await loadRef.current())
      setError(null)
    } catch (e) {
      setError(e as Error)
    }
  }, [])

  // deps are supplied by the caller
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    setData(null)
    void reload()
    if (!intervalMs) return
    const id = setInterval(() => void reload(), intervalMs)
    return () => clearInterval(id)
  }, deps)
  /* eslint-enable react-hooks/exhaustive-deps */

  return { data, error, reload }
}

/** Runs an async action, tracking busy state and the last error message. */
export function useAction() {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = useCallback(async <T,>(fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(true)
    setError(null)
    try {
      return await fn()
    } catch (e) {
      setError((e as Error).message)
      return undefined
    } finally {
      setBusy(false)
    }
  }, [])
  return { busy, error, run, clearError: () => setError(null) }
}
