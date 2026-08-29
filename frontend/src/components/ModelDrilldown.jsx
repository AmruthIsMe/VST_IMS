import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend,
  CartesianGrid, ReferenceLine,
} from 'recharts';
import { Activity, TrendingDown, TrendingUp, Database, Award, Layers, RefreshCw } from 'lucide-react';
import { getTrainingHistory } from '../services/api';

const MODEL_ORDER = ['xgboost', 'lightgbm', 'arima', 'sarima', 'prophet', 'holt_winters'];
const MODEL_META = {
  xgboost: { color: '#2563eb', label: 'XGBoost' },
  lightgbm: { color: '#7c3aed', label: 'LightGBM' },
  arima: { color: '#0d9488', label: 'ARIMA' },
  sarima: { color: '#e9730c', label: 'SARIMA' },
  prophet: { color: '#db2777', label: 'Prophet' },
  holt_winters: { color: '#64748b', label: 'Holt-Winters' },
};

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' }) + ' ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function DeltaBadge({ value, suffix = '', invert = false }) {
  if (value == null || isNaN(value)) return <span style={{ color: '#98a2b3', fontSize: 11 }}>—</span>;
  const good = invert ? value < 0 : value > 0;
  const flat = Math.abs(value) < 0.005;
  const color = flat ? '#667085' : good ? '#027a48' : '#b42318';
  const bg = flat ? '#f2f4f7' : good ? '#ecfdf3' : '#fef3f2';
  const arrow = flat ? '→' : value > 0 ? '▲' : '▼';
  return (
    <span style={{
      padding: '1px 8px', borderRadius: 10, fontSize: 11, fontWeight: 700,
      backgroundColor: bg, color, border: `1px solid ${flat ? '#eaecf0' : good ? '#a6f4c5' : '#fecdca'}`,
      fontFamily: 'monospace',
    }}>
      {arrow} {value > 0 ? '+' : ''}{Number(value).toFixed(2)}{suffix}
    </span>
  );
}

export default function ModelDrilldown() {
  const [selectedIdx, setSelectedIdx] = useState(null);

  const { data, isLoading } = useQuery({
    queryKey: ['training-history'],
    queryFn: () => getTrainingHistory({ limit: 50 }).then(r => r.data),
  });

  const runs = data?.runs || [];
  // runs are newest-first; chronological order for charts
  const chrono = useMemo(() => [...runs].reverse(), [runs]);
  const selected = selectedIdx != null
    ? runs.find(r => r.index === selectedIdx) || runs[0]
    : runs[0];

  const mapeSeries = useMemo(() => chrono.map(run => {
    const point = { date: fmtDate(run.date), ensemble: run.ensemble_mape };
    MODEL_ORDER.forEach(m => {
      const v = run.per_model?.[m]?.mape;
      if (v != null) point[m] = v;
    });
    return point;
  }), [chrono]);

  const weightSeries = useMemo(() => chrono.map(run => {
    const point = { date: fmtDate(run.date) };
    MODEL_ORDER.forEach(m => {
      const w = run.weights?.[m];
      point[m] = w != null ? Number((w * 100).toFixed(2)) : 0;
    });
    return point;
  }), [chrono]);

  if (isLoading) {
    return (
      <div className="loading"><RefreshCw size={20} className="spin" style={{ marginRight: 8 }} />
        Loading training history...</div>
    );
  }

  if (!runs.length) {
    return (
      <div className="forecast-empty-state">
        <Activity size={48} strokeWidth={1.5} />
        <h3>No Training History Yet</h3>
        <p>Run "Sync All &amp; Retrain" or train models to start building history.</p>
      </div>
    );
  }

  // ── Narrative for the selected run ──
  const pm = selected.per_model || {};
  const trained = MODEL_ORDER.filter(m => pm[m]?.status === 'trained');
  const withDeltas = trained.filter(m => pm[m]?.mape_delta != null);
  const best = trained.length ? trained.reduce((a, b) => (pm[a].mape ?? 999) <= (pm[b].mape ?? 999) ? a : b) : null;
  const worst = trained.length > 1 ? trained.reduce((a, b) => (pm[a].mape ?? -1) >= (pm[b].mape ?? -1) ? a : b) : null;
  const biggestMover = withDeltas.length
    ? withDeltas.reduce((a, b) => Math.abs(pm[a].mape_delta) >= Math.abs(pm[b].mape_delta) ? a : b)
    : null;
  const biggestWeightShift = trained.filter(m => pm[m]?.weight_delta != null).length
    ? trained.filter(m => pm[m]?.weight_delta != null)
        .reduce((a, b) => Math.abs(pm[a].weight_delta) >= Math.abs(pm[b].weight_delta) ? a : b)
    : null;
  const improvements = withDeltas.filter(m => pm[m].improved);
  const regressions = withDeltas.filter(m => pm[m].improved === false);

  return (
    <div className="forecast-overview">
      {/* ═══ Runs Timeline Table ═══ */}
      <div className="card-table-container" style={{ marginBottom: 14 }}>
        <div className="table-card-header">
          <div className="table-card-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <Layers size={20} color="#2563eb" />
            Training Run Timeline
            <span style={{ fontSize: 12, color: '#667085', fontWeight: 400 }}>
              — {data.total_runs} runs recorded · click a row to drill down
            </span>
          </div>
        </div>
        <div style={{ maxHeight: 260, overflowY: 'auto' }}>
          <table className="data-table">
            <thead>
              <tr>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Run</th>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Date</th>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Models Trained</th>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Ensemble MAPE</th>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Δ vs Previous</th>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Train Rows</th>
                <th style={{ padding: '8px 12px', fontSize: 11 }}>Elapsed</th>
              </tr>
            </thead>
            <tbody>
              {runs.map(run => {
                const isSel = selected?.index === run.index;
                const trainRows = run.dataset?.train_rows;
                return (
                  <tr key={run.index}
                    onClick={() => setSelectedIdx(run.index)}
                    style={{ cursor: 'pointer', backgroundColor: isSel ? '#eff8ff' : 'inherit' }}
                  >
                    <td style={{ padding: '6px 12px', fontWeight: 700, fontFamily: 'monospace', fontSize: 11, color: isSel ? '#2563eb' : undefined }}>
                      #{run.index + 1}{isSel ? ' ●' : ''}
                    </td>
                    <td style={{ padding: '6px 12px', fontSize: 11 }}>{fmtDate(run.date)}</td>
                    <td style={{ padding: '6px 12px', fontWeight: 600, fontSize: 11 }}>{run.models_trained}/6</td>
                    <td style={{ padding: '6px 12px', fontWeight: 700, fontSize: 11 }}>
                      {run.ensemble_mape != null ? `${run.ensemble_mape}%` : '—'}
                    </td>
                    <td style={{ padding: '6px 12px' }}><DeltaBadge value={run.ensemble_mape_delta} suffix="%" /></td>
                    <td style={{ padding: '6px 12px', fontSize: 11, color: '#667085' }}>
                      {trainRows != null ? trainRows.toLocaleString() : '—'}
                    </td>
                    <td style={{ padding: '6px 12px', fontSize: 11, color: '#667085' }}>{run.elapsed_seconds}s</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {selected && (
        <>
          {/* ═══ KPI Cards ═══ */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 14 }}>
            <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <Activity size={15} color="#2563eb" />
                <span style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Ensemble MAPE</span>
              </div>
              <div style={{ fontSize: 22, fontWeight: 800, color: '#1a1d1a', lineHeight: 1.2 }}>
                {selected.ensemble_mape != null ? `${selected.ensemble_mape}%` : '—'}
              </div>
              <div style={{ marginTop: 4 }}><DeltaBadge value={selected.ensemble_mape_delta} suffix="%" invert /></div>
            </div>
            <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <Award size={15} color="#b54708" />
                <span style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Best Model (lowest MAPE)</span>
              </div>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#1a1d1a', lineHeight: 1.3 }}>
                {best ? MODEL_META[best].label : '—'}
              </div>
              <div style={{ fontSize: 11, color: '#667085', fontFamily: 'monospace' }}>
                {best && pm[best]?.mape != null ? `MAPE ${pm[best].mape}% · weight ${((pm[best].weight || 0) * 100).toFixed(1)}%` : ''}
              </div>
            </div>
            <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <TrendingDown size={15} color="#027a48" />
                <span style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Biggest Improvement</span>
              </div>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#027a48', lineHeight: 1.3 }}>
                {biggestMover && pm[biggestMover].mape_delta > 0 ? MODEL_META[biggestMover].label : 'None'}
              </div>
              {biggestMover && pm[biggestMover].mape_delta > 0 && (
                <div style={{ fontSize: 11, color: '#027a48', fontFamily: 'monospace' }}>
                  −{pm[biggestMover].mape_delta.toFixed(2)}pp MAPE
                </div>
              )}
            </div>
            <div style={{ padding: '12px 14px', borderRadius: 10, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                <Database size={15} color="#7c3aed" />
                <span style={{ fontSize: 11, color: '#667085', fontWeight: 600 }}>Training Data</span>
              </div>
              <div style={{ fontSize: 16, fontWeight: 800, color: '#1a1d1a', lineHeight: 1.3 }}>
                {selected.dataset?.train_rows != null ? `${selected.dataset.train_rows.toLocaleString()} rows` : 'Not recorded'}
              </div>
              <div style={{ fontSize: 11, color: '#667085' }}>
                {selected.dataset
                  ? `test ${selected.dataset.test_rows?.toLocaleString()} · split @ ${selected.dataset.split_date || '—'}`
                  : 'legacy run'}
              </div>
            </div>
          </div>

          {/* ═══ What Changed Narrative ═══ */}
          <div style={{
            padding: '14px 18px', borderRadius: 12, marginBottom: 14,
            border: '1px solid #eaecf0', backgroundColor: '#fff',
          }}>
            <div style={{ fontSize: 13, fontWeight: 800, color: '#1a1d1a', marginBottom: 8 }}>
              What changed in this training — {fmtDate(selected.date)}
            </div>
            {selected.error ? (
              <div style={{ fontSize: 12, color: '#b42318' }}>⚠ Training failed: {selected.error}</div>
            ) : !withDeltas.length ? (
              <div style={{ fontSize: 12, color: '#667085' }}>
                Per-model metrics were not recorded for this run (recorded automatically from now on).
                Weight snapshot only.
              </div>
            ) : (
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12, color: '#344054', lineHeight: 1.9 }}>
                <li><strong>{selected.models_trained}/6 models</strong> retrained
                  {selected.ensemble_mape_delta != null && (
                    <> — ensemble MAPE {selected.ensemble_mape_delta >= 0 ? 'improved' : 'degraded'} by <strong>{Math.abs(selected.ensemble_mape_delta)}pp</strong> → {selected.ensemble_mape}%</>
                  )}
                </li>
                {best && <li><strong>{MODEL_META[best].label}</strong> leads accuracy at <strong>{pm[best].mape}% MAPE</strong></li>}
                {!!improvements.length && (
                  <li>Improved: {improvements.map(m =>
                    <strong key={m} style={{ color: '#027a48' }}> {MODEL_META[m].label} ({pm[m].mape_delta > 0 ? '+' : ''}{pm[m].mape_delta}pp)</strong>)}
                  </li>
                )}
                {!!regressions.length && (
                  <li>Regressed: {regressions.map(m =>
                    <strong key={m} style={{ color: '#b42318' }}> {MODEL_META[m].label} ({pm[m].mape_delta}pp)</strong>)}
                  </li>
                )}
                {biggestWeightShift && Math.abs(pm[biggestWeightShift].weight_delta) > 0.001 && (
                  <li>Ensemble trust shifted most toward/away from <strong>{MODEL_META[biggestWeightShift].label}</strong>
                    {' '}({pm[biggestWeightShift].weight_delta > 0 ? '+' : ''}{(pm[biggestWeightShift].weight_delta * 100).toFixed(1)}pp weight
                    → {(pm[biggestWeightShift].weight * 100).toFixed(1)}%)</li>
                )}
                {worst && best !== worst && (
                  <li>Weakest performer: <strong>{MODEL_META[worst].label}</strong> at {pm[worst]?.mape}% MAPE</li>
                )}
                {!improvements.length && !regressions.length && withDeltas.length > 0 && (
                  <li>All model errors held steady (±0.05pp) — new data confirmed current patterns.</li>
                )}
              </ul>
            )}
          </div>

          {/* ═══ Charts ═══ */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14, marginBottom: 14 }}>
            <div style={{ padding: '14px 16px', borderRadius: 12, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: '#1a1d1a', marginBottom: 2 }}>
                Model MAPE Across Training Runs
              </div>
              <div style={{ fontSize: 11, color: '#667085', marginBottom: 10 }}>
                Lower is better — how each model learns as new SAP data arrives
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={mapeSeries} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f2f4f7" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v, i) => (i % 2 === 0 ? v : '')} />
                  <YAxis tick={{ fontSize: 10 }} unit="%" width={50} />
                  <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <ReferenceLine y={10} stroke="#fecdca" strokeDasharray="4 4" label={{ value: 'target 10%', fontSize: 9, fill: '#b42318' }} />
                  {MODEL_ORDER.map(m => (
                    <Line key={m} type="monotone" dataKey={m} name={MODEL_META[m].label}
                      stroke={MODEL_META[m].color} strokeWidth={2} dot={false} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>

            <div style={{ padding: '14px 16px', borderRadius: 12, border: '1px solid #eaecf0', backgroundColor: '#fff' }}>
              <div style={{ fontSize: 13, fontWeight: 800, color: '#1a1d1a', marginBottom: 2 }}>
                Ensemble Weight Evolution
              </div>
              <div style={{ fontSize: 11, color: '#667085', marginBottom: 10 }}>
                How much the ensemble trusts each model over time (%)
              </div>
              <ResponsiveContainer width="100%" height={240}>
                <LineChart data={weightSeries} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f2f4f7" />
                  <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v, i) => (i % 2 === 0 ? v : '')} />
                  <YAxis tick={{ fontSize: 10 }} unit="%" width={50} />
                  <Tooltip contentStyle={{ fontSize: 11, borderRadius: 8 }}
                    formatter={(v) => `${Number(v).toFixed(2)}%`} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  {MODEL_ORDER.map(m => (
                    <Line key={m} type="monotone" dataKey={m} name={MODEL_META[m].label}
                      stroke={MODEL_META[m].color} strokeWidth={2} dot={false} connectNulls />
                  ))}
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* ═══ Per-Model Delta Table ═══ */}
          <div className="card-table-container">
            <div className="table-card-header">
              <div className="table-card-title" style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <TrendingUp size={18} color="#2563eb" />
                Per-Model Breakdown vs Previous Run
              </div>
            </div>
            <table className="data-table">
              <thead>
                <tr>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Model</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Status</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>MAPE</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Δ MAPE</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>RMSE</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Bias</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Weight</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Δ Weight</th>
                  <th style={{ padding: '8px 12px', fontSize: 11 }}>Verdict</th>
                </tr>
              </thead>
              <tbody>
                {MODEL_ORDER.map(m => {
                  const info = pm[m] || { status: 'not_run' };
                  const meta = MODEL_META[m];
                  let verdict = <span style={{ color: '#98a2b3', fontSize: 11 }}>No history</span>;
                  if (info.improved === true) verdict = <span style={{ color: '#027a48', fontWeight: 700, fontSize: 11 }}>Improved</span>;
                  else if (info.improved === false) verdict = <span style={{ color: '#b42318', fontWeight: 700, fontSize: 11 }}>Regressed</span>;
                  else if (info.mape != null) verdict = <span style={{ color: '#667085', fontSize: 11 }}>Stable</span>;
                  else if (info.status === 'failed') verdict = <span style={{ color: '#b42318', fontSize: 11 }}>Failed</span>;
                  return (
                    <tr key={m}>
                      <td style={{ padding: '7px 12px' }}>
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
                          <span style={{ width: 9, height: 9, borderRadius: 2, backgroundColor: meta.color }} />
                          <strong style={{ fontFamily: 'monospace', fontSize: 11 }}>{meta.label}</strong>
                        </span>
                      </td>
                      <td style={{ padding: '7px 12px', fontSize: 11 }}>
                        <span style={{
                          padding: '2px 8px', borderRadius: 10, fontSize: 10, fontWeight: 700,
                          backgroundColor: info.status === 'trained' ? '#ecfdf3' : info.status === 'failed' ? '#fef3f2' : '#f9fafb',
                          color: info.status === 'trained' ? '#027a48' : info.status === 'failed' ? '#b42318' : '#667085',
                        }}>
                          {info.status || '—'}
                        </span>
                      </td>
                      <td style={{ padding: '7px 12px', fontWeight: 700, fontSize: 11 }}>
                        {info.mape != null ? `${info.mape}%` : '—'}
                      </td>
                      <td style={{ padding: '7px 12px' }}><DeltaBadge value={info.mape_delta} suffix="%" /></td>
                      <td style={{ padding: '7px 12px', fontSize: 11, color: '#667085' }}>
                        {info.rmse != null ? Number(info.rmse).toFixed(2) : '—'}
                      </td>
                      <td style={{ padding: '7px 12px', fontSize: 11, color: '#667085' }}>
                        {info.bias != null ? `${info.bias > 0 ? '+' : ''}${info.bias}%` : '—'}
                      </td>
                      <td style={{ padding: '7px 12px', fontWeight: 600, fontSize: 11 }}>
                        {info.weight != null ? `${(info.weight * 100).toFixed(1)}%` : '—'}
                      </td>
                      <td style={{ padding: '7px 12px' }}><DeltaBadge value={info.weight_delta != null ? Number((info.weight_delta * 100).toFixed(2)) : null} suffix="pp" /></td>
                      <td style={{ padding: '7px 12px' }}>{verdict}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
