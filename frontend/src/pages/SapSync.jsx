import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSapSyncStatus, testSapConnection, syncAll, checkSapMockStatus, getTrainingStatus } from '../services/api';
import Header from '../components/Header';
import { Database, RefreshCw, CheckCircle, XCircle, Zap, Server, ExternalLink, Play, Copy, Check, BadgeCheck } from 'lucide-react';

export default function SapSync({ onMenuToggle }) {
  const qc = useQueryClient();
  const [syncProgress, setSyncProgress] = useState(null);
  const [debugLog, setDebugLog] = useState(null);
  const [copied, setCopied] = useState(false);
  const [forecastReady, setForecastReady] = useState(false);
  const [recentlySynced, setRecentlySynced] = useState(false);

  const { data: status } = useQuery({
    queryKey: ['sap-sync-status'],
    queryFn: () => getSapSyncStatus().then((r) => r.data),
    refetchInterval: 5000,
  });

  const { data: mockStatus } = useQuery({
    queryKey: ['sap-mock-status'],
    queryFn: () => checkSapMockStatus().then((r) => r.data),
    refetchInterval: 5000,
  });

  const { data: trainingStatus } = useQuery({
    queryKey: ['training-status'],
    queryFn: () => getTrainingStatus().then((r) => r.data),
    refetchInterval: (query) => {
      const data = query.state.data;
      if (syncProgress) return 2000;
      if (recentlySynced) return 2000;
      if (data?.status === 'training') return 2000;
      return false;
    },
  });

  useEffect(() => {
    if (trainingStatus && (trainingStatus.status === 'completed' || trainingStatus.status === 'failed')) {
      setRecentlySynced(false);
    }
  }, [trainingStatus]);

  const syncAllMut = useMutation({
    mutationFn: () => {
      setSyncProgress({ stage: 'syncing' });
      setDebugLog(null);
      setForecastReady(false);
      return syncAll();
    },
    onSuccess: (r) => {
      setSyncProgress({ stage: 'retraining', result: r.data });
      setRecentlySynced(true);
      const now = new Date().toISOString();
      const details = r.data.details || {};
      const lines = [
        `=== SAP SYNC + RETRAIN REPORT ===`,
        `Timestamp: ${now}`,
        `Overall Status: ${r.data.status}`,
        `Total Records Synced: ${r.data.records_synced}`,
        `ML Retrain: ${r.data.retrain}`,
        ``,
        `--- MODULE DETAILS ---`,
      ];
      const fmtW = (w) => Object.entries(w || {}).map(([k, v]) => `${k}=${(v * 100).toFixed(1)}%`).join(' ');
      for (const [mod, info] of Object.entries(details)) {
        const st = info.status === 'completed' ? '[OK]' : info.status === 'failed' ? '[FAIL]' : '[WARN]';
        if (typeof info.orders_fetched === 'number') {
          lines.push(`${st} ${mod}: +${info.records_synced} rows inserted from SAP (fetched=${info.orders_fetched}, dupes=${info.duplicates_skipped ?? 0})`);
          const bf = info.backfill_to_today;
          if (bf && !bf.error) {
            lines.push(`     simulated to today: +${bf.simulated_rows_inserted ?? 0} rows inserted, ${bf.simulated_rows_updated ?? 0} live-week rows updated (coverage → ${bf.coverage_to ?? 'n/a'})`);
          } else if (bf?.error) {
            lines.push(`     backfill failed: ${bf.error}`);
          }
        } else if (typeof info.pairs_evaluated === 'number') {
          lines.push(`${st} ${mod}: ${info.message}`);
          if (info.blended_weights && Object.keys(info.blended_weights).length) {
            lines.push(`     blended weights: ${fmtW(info.blended_weights)}`);
          }
        } else if (typeof info.models_trained === 'number') {
          lines.push(`${st} ${mod}: ${info.models_trained}/6 models · ensemble MAPE ${info.ensemble_mape ?? 'N/A'}% · ${info.elapsed_seconds ?? '?'}s`);
          if (info.weights) lines.push(`     new weights: ${fmtW(info.weights)}`);
        } else if (typeof info.rows_stored === 'number') {
          lines.push(`${st} ${mod}: ${info.message} window: ${info.forecast_window ?? ''}`);
        } else if (typeof info.records_synced === 'number') {
          lines.push(`${st} ${mod}: ${info.records_synced} records`);
        } else {
          lines.push(`${st} ${mod}: ${JSON.stringify(info).slice(0, 160)}`);
        }
        if (info.error) lines.push(`    Error: ${info.error}`);
      }
      setDebugLog(lines.join('\n'));
      qc.invalidateQueries(['sap-sync-status']);
      qc.invalidateQueries(['forecast-products']);
      qc.invalidateQueries(['sku-explorer']);
      qc.invalidateQueries(['reorder-recs']);
      qc.invalidateQueries(['forecast-compare']);
      setTimeout(() => {
        setSyncProgress(null);
        setForecastReady(true);
      }, 4000);
    },
    onError: (err) => {
      const now = new Date().toISOString();
      const detail = err.response?.data?.detail || err.message || 'Unknown error';
      setDebugLog([
        `=== SAP SYNC REPORT ===`,
        `Timestamp: ${now}`,
        `Overall Status: FAILED`,
        ``,
        `--- ERROR ---`,
        detail,
      ].join('\n'));
      setSyncProgress(null);
    },
  });

  const testMut = useMutation({
    mutationFn: () => testSapConnection(),
  });

  const isConnected = status?.connected || mockStatus?.connected;

  const copyLog = () => {
    if (!debugLog) return;
    navigator.clipboard.writeText(debugLog).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div>
      <Header locationText="SAP ERP Integration — Live Sync" onMenuToggle={onMenuToggle} />

      <div className="page-container">
        <div className="page-banner" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div className="page-banner-icon">
              <Database size={24} />
            </div>
            <h1 className="page-banner-title">SAP ERP Sync</h1>
          </div>

          <button className="btn-primary" onClick={() => testMut.mutate()} disabled={testMut.isPending}>
            {testMut.isPending ? 'Testing Connection...' : 'Test SAP Connection'}
          </button>
        </div>

        {/* Connection Status KPIs */}
        <div className="kpi-grid" style={{ marginBottom: 24 }}>
          <div className="kpi-card">
            <div className="kpi-label">Connection Status</div>
            <div className="kpi-value" style={{ fontSize: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
              {isConnected ? (
                <><CheckCircle size={22} color="var(--primary)" /> Connected</>
              ) : (
                <><XCircle size={22} color="var(--danger-text)" /> Not Configured</>
              )}
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-label">SAP System</div>
            <div className="kpi-value" style={{ fontSize: 16, display: 'flex', alignItems: 'center', gap: 8 }}>
              <Server size={18} />
              {mockStatus?.connected ? (
                <span>{mockStatus.plant_name || 'Plant 1000'}</span>
              ) : (
                <span>{status?.connected ? 'Real SAP' : 'Not Connected'}</span>
              )}
            </div>
            {mockStatus?.connected && (
              <div style={{ fontSize: 11, color: '#667085', marginTop: 4 }}>
                {mockStatus.materials_count} materials | {mockStatus.stock_records} stock records | {mockStatus.sales_orders} sales orders
              </div>
            )}
          </div>

          <div className="kpi-card">
            <div className="kpi-label">Last Sync</div>
            <div className="kpi-value" style={{ fontSize: 18 }}>
              {status?.last_sync ? new Date(status.last_sync).toLocaleString() : 'Never'}
            </div>
          </div>
        </div>

        {/* Sync Progress Banner */}
        {syncProgress && (
          <div className="forecast-status-banner training">
            <RefreshCw size={18} className="spin" />
            {syncProgress.stage === 'syncing' && 'Syncing SAP data, evaluating forecasts against new actuals (RL feedback), then retraining models — this can take up to ~90s...'}
            {syncProgress.stage === 'retraining' && 'Retraining ML models with UCB1 feedback loop...'}
          </div>
        )}

        {/* Forecast Ready Badge */}
        {forecastReady && !syncProgress && (
          <div style={{
            padding: '12px 20px', borderRadius: 10, marginBottom: 20,
            backgroundColor: '#ecfdf3', border: '1px solid #a6f4c5',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <BadgeCheck size={20} color="#027a48" />
              <span style={{ fontSize: 14, fontWeight: 700, color: '#027a48' }}>
                Forecast Ready — Models retrained with latest SAP data
              </span>
            </div>
            <button
              onClick={() => setForecastReady(false)}
              style={{
                padding: '4px 12px', borderRadius: 6, border: '1px solid #a6f4c5',
                backgroundColor: '#fff', cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#027a48',
              }}
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Training Progress Panel */}
        {trainingStatus && trainingStatus.status !== 'idle' && (
          <div style={{
            borderRadius: 14, border: '1px solid #eaecf0', backgroundColor: '#fff',
            boxShadow: '0 2px 8px rgba(0,0,0,0.06)', marginBottom: 24, overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 20px', borderBottom: '1px solid #eaecf0',
              backgroundColor: trainingStatus.status === 'training' ? '#fffaeb' : '#ecfdf3',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                {trainingStatus.status === 'training' ? (
                  <RefreshCw size={18} className="spin" color="#b54708" />
                ) : (
                  <BadgeCheck size={18} color="#027a48" />
                )}
                <span style={{ fontSize: 14, fontWeight: 700, color: trainingStatus.status === 'training' ? '#b54708' : '#027a48' }}>
                  {trainingStatus.status === 'training' ? 'Training Models...' : trainingStatus.status === 'completed' ? 'Training Complete' : 'Training Failed'}
                </span>
              </div>
              <span style={{ fontSize: 12, color: '#667085' }}>
                {trainingStatus.models_completed}/{trainingStatus.total_models} models · {trainingStatus.elapsed_seconds}s
              </span>
            </div>

            {/* Progress Bar */}
            <div style={{ padding: '12px 20px', borderBottom: '1px solid #f2f4f7' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                <span style={{ fontSize: 11, color: '#667085' }}>Progress</span>
                <span style={{ fontSize: 11, fontWeight: 600, color: '#1a1d1a' }}>
                  {Math.round((trainingStatus.models_completed / trainingStatus.total_models) * 100)}%
                </span>
              </div>
              <div style={{ height: 6, backgroundColor: '#f2f4f7', borderRadius: 3, overflow: 'hidden' }}>
                <div style={{
                  height: '100%',
                  width: `${(trainingStatus.models_completed / trainingStatus.total_models) * 100}%`,
                  backgroundColor: trainingStatus.status === 'training' ? '#e9730c' : '#10b149',
                  borderRadius: 3,
                  transition: 'width 0.5s ease',
                }} />
              </div>
            </div>

            {/* Per-Model Status */}
            <div style={{ padding: '12px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                {['xgboost', 'lightgbm', 'arima', 'sarima', 'prophet', 'holt_winters'].map((model) => {
                  const info = trainingStatus.models?.[model];
                  const status = info?.status || 'pending';
                  return (
                    <div key={model} style={{
                      padding: '8px 12px', borderRadius: 8,
                      border: `1px solid ${status === 'completed' ? '#a6f4c5' : status === 'failed' ? '#fecdca' : status === 'training' ? '#fedf89' : '#eaecf0'}`,
                      backgroundColor: status === 'completed' ? '#ecfdf3' : status === 'failed' ? '#fef3f2' : status === 'training' ? '#fffaeb' : '#f9fafb',
                    }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'monospace', color: '#1a1d1a' }}>{model}</span>
                        {status === 'completed' && <Check size={14} color="#027a48" />}
                        {status === 'failed' && <XCircle size={14} color="#dc2626" />}
                        {status === 'training' && <RefreshCw size={14} className="spin" color="#b54708" />}
                      </div>
                      {info?.elapsed_seconds > 0 && (
                        <div style={{ fontSize: 10, color: '#667085' }}>{info.elapsed_seconds}s</div>
                      )}
                      {info?.metrics?.mape != null && (
                        <div style={{ fontSize: 10, color: '#667085' }}>MAPE: {info.metrics.mape}%</div>
                      )}
                      {info?.error && (
                        <div style={{ fontSize: 10, color: '#dc2626', marginTop: 2, wordBreak: 'break-word' }}>{info.error}</div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        )}

        {/* SAP Mock ERP not running hint */}
        {!mockStatus?.connected && (
          <div style={{
            padding: '12px 20px', borderRadius: 10, marginBottom: 20,
            backgroundColor: '#eff8ff', border: '1px solid #b4cff5',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Server size={18} color="#175cd3" />
              <span style={{ fontSize: 13, fontWeight: 600, color: '#175cd3' }}>
                Cloud Mode — Sync generates data from demand profiles (no SAP connection required).
              </span>
            </div>
            <span style={{ fontSize: 11, color: '#667085', fontFamily: 'monospace' }}>
              Data is simulated using historical patterns
            </span>
          </div>
        )}

        {/* SAP Mock ERP Quick Link */}
        {mockStatus?.connected && (
          <div style={{
            padding: '12px 20px', borderRadius: 10, marginBottom: 20,
            backgroundColor: '#ecfdf3', border: '1px solid #a6f4c5',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <Zap size={18} color="#027a48" />
              <span style={{ fontSize: 13, fontWeight: 600, color: '#027a48' }}>
                SAP Mock ERP is running on port 8001
              </span>
            </div>
            <a
              href="http://localhost:8001"
              target="_blank"
              rel="noopener noreferrer"
              style={{
                display: 'flex', alignItems: 'center', gap: 4,
                fontSize: 12, fontWeight: 600, color: '#027a48', textDecoration: 'none',
              }}
            >
              Open SAP Console <ExternalLink size={12} />
            </a>
          </div>
        )}

        {/* Single Sync All Button */}
        <div style={{
          padding: '32px', borderRadius: 14, border: '1px solid #eaecf0', backgroundColor: '#fff',
          boxShadow: '0 2px 8px rgba(0,0,0,0.06)', textAlign: 'center', marginBottom: 24,
        }}>
          <Database size={40} color="#667085" style={{ marginBottom: 12 }} />
          <h2 style={{ fontSize: 20, fontWeight: 800, margin: '0 0 8px 0', color: '#1a1d1a' }}>
            Sync All SAP Data
          </h2>
          <p style={{ fontSize: 13, color: '#667085', margin: '0 0 20px 0', maxWidth: 500, marginLeft: 'auto', marginRight: 'auto' }}>
            Syncs Materials, Vendors, Stocks, Orders and Sales from SAP, then retrains ML models with UCB1 feedback loop.
          </p>
          <button
            className="btn-primary"
            style={{
              padding: '14px 48px', fontSize: 16, fontWeight: 700, borderRadius: 10,
              display: 'inline-flex', alignItems: 'center', gap: 10,
            }}
            onClick={() => syncAllMut.mutate()}
            disabled={syncAllMut.isPending || !isConnected}
          >
            {syncAllMut.isPending ? (
              <><RefreshCw size={18} className="spin" /> Syncing & Retraining...</>
            ) : (
              <><Play size={18} /> Sync All & Retrain</>
            )}
          </button>
        </div>

        {/* Debug Log Report */}
        {debugLog && (
          <div style={{
            borderRadius: 14, border: '1px solid #eaecf0', backgroundColor: '#fff',
            boxShadow: '0 2px 8px rgba(0,0,0,0.06)', marginBottom: 24, overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 20px', borderBottom: '1px solid #eaecf0', backgroundColor: '#f9fafb',
            }}>
              <span style={{ fontSize: 14, fontWeight: 700, color: '#1a1d1a' }}>Sync Debug Report</span>
              <button
                onClick={copyLog}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6, padding: '6px 14px',
                  borderRadius: 6, border: '1px solid #eaecf0', backgroundColor: '#fff',
                  cursor: 'pointer', fontSize: 12, fontWeight: 600, color: '#344054',
                }}
              >
                {copied ? <><Check size={14} color="#027a48" /> Copied!</> : <><Copy size={14} /> Copy Log</>}
              </button>
            </div>
            <pre style={{
              margin: 0, padding: '16px 20px', fontSize: 12, fontFamily: 'monospace',
              lineHeight: 1.6, backgroundColor: '#1e1e1e', color: '#d4d4d4',
              overflowX: 'auto', maxHeight: 300, overflowY: 'auto',
            }}>
              {debugLog}
            </pre>
          </div>
        )}

        {/* Sync Operations Log */}
        <div className="card-table-container">
          <div className="table-card-header">
            <div className="table-card-title">Sync Operations Log</div>
          </div>

          <table className="data-table">
            <thead>
              <tr>
                <th>Module</th>
                <th>Status</th>
                <th>Records</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {(status?.recent_logs || []).length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: 30, color: '#667085' }}>
                    No sync operations executed yet
                  </td>
                </tr>
              )}
              {(status?.recent_logs || []).map((log) => (
                <tr key={log.id}>
                  <td style={{ fontWeight: 700 }}>{log.sync_type}</td>
                  <td>
                    {log.status === 'completed' ? <span className="badge-pill badge-healthy">Completed</span> : <span className="badge-pill badge-low">In Progress</span>}
                  </td>
                  <td style={{ fontWeight: 600 }}>{log.records_synced}</td>
                  <td style={{ color: '#667085' }}>{new Date(log.started_at).toLocaleString()}</td>
                  <td style={{ color: '#667085' }}>{log.completed_at ? new Date(log.completed_at).toLocaleString() : '—'}</td>
                  <td style={{ color: '#d32f2f' }}>{log.error_message || '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
