import { DEFAULT_QUALITY, DEFAULT_TARGET_VMAF } from '../api'

/** Output quality: automatic (null, searched per file for VMAF 95) or a fixed QVBR value. */
export function QualityField({ value, onChange }: { value: number | null; onChange: (q: number | null) => void }) {
  return (
    <label title="Auto: pro Datei die kleinste Datei suchen, die noch VMAF 95 erreicht (optisch wie unkomprimiert). Fest: QVBR, kleiner = bessere Qualität, größere Datei">
      Qualität
      <span className="row">
        <select value={value === null ? 'auto' : 'fixed'} onChange={(e) => onChange(e.target.value === 'auto' ? null : DEFAULT_QUALITY)}>
          <option value="auto">Auto (VMAF {DEFAULT_TARGET_VMAF})</option>
          <option value="fixed">Fest</option>
        </select>
        {value !== null && (
          <input type="number" min={1} max={63} value={value} onChange={(e) => onChange(Number(e.target.value))} />
        )}
      </span>
    </label>
  )
}
