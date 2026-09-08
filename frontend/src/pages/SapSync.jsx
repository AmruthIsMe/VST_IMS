import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSapSyncStatus, testSapConnection, syncAndRetrain, checkSapMockStatus, getTrainingStatus, getLastTrainingInfo } from '../services/api';
import Header from '../components/Header';
import { Database, RefreshCw, CheckCircle, XCircle, Zap, Server, ExternalLink, Play, Copy, Check, BadgeCheck, Clock, Cpu, TrendingUp, AlertTriangle } from 'lucide-react';

export default function SapSync({ onMenuToggle }) {
  const qc = useQueryClient();
  const [syncProgress, setSyncProgress] = useState(null);
  const [resultMessage, setResultMessage] = useState(null);

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
      if (syncProgress) return 2000;
      const data = query.state.data;
      if (data?.status === 'training') return 2000;
      return 5000;
    },
  });

  const { data: lastTraining } = useQuery({
    queryKey: ['last-training-info'],
    queryFn: () => getLastTrainingInfo().then((r) => r.data),
    refetchInterval: 10000,
  });

  const retrainMut = useMutation({
    mutationFn: () => {
      setSyncProgress({ stage: 'starting' });
      setResultMessage(null);
      return syncAndRetrain();
    },
    onSuccess: (r) => {
      const details = r.data.details || {};
      const training = details.training || {};
      const forecast = details.forecast || {};
      const rl = details.rl_feedback || {};

      if (training.status === 'completed') {
        setResultMessage({
          type: 'success',
          title: 'Sync & Retrain Complete',
          text: `Trained ${training.models_trained}/6 models in ${training.elapsed_seconds}s. Ensemble MAPE: ${training.ensemble_mape}%. ${forecast.rows_stored || 0} predictions generated for ${training.sku_count || 0} SKUs.`,
        });
      } else if (training.status === 'skipped') {
        setResultMessage({
          type: 'info',
          title: 'Sync Complete (Training Skipped)',
          text: training.message || 'Training was skipped. Data synced and RL evaluation completed.',
        });
      } else if (training.status === 'failed') {
        setResultMessage({
          type: 'error',
          title: 'Training Failed',
          text: training.error || 'An error occurred during training. Check the logs.',
        });
      } else {
        setResultMessage({
          type: 'info',
          title: 'Sync Complete',
          text: `Data synced. ${rl.pairs_evaluated || 0} forecast pairs evaluated.`,
        });
      }

      setSyncProgress(null);
      qc.invalidateQueries(['sap-sync-status']);
      qc.invalidateQueries(['last-training-info']);
      qc.invalidateQueries(['training-history']);
      qc.invalidateQueries(['forecast-products']);
      qc.invalidateQueries(['sku-explorer']);
    },
    onError: (err) => {
      const detail = err.response?.data?.detail || err.message || 'Unknown error';
      setResultMessage({
        type: 'error',
        title: 'Sync Failed',
        text: detail,
      });
      setSyncProgress(null);
    },
  });

  const testMut = useMutation({
    mutationFn: () => testSapConnection(),
  });

  const isConnected = status?.connected || mockStatus?.connected;

  const formatTimeAgo = (isoString) => {
    if (!isoString) return 'Never';
    const diff = Date.now() - new Date(isoString).getTime();
    const hours = Math.floor(diff / 3600000);
    const days = Math.floor(hours / 24);
    if (days > 0) return `${days}d ${hours % 24}h ago`;
    if (hours > 0) return `${hours}h ago`;
    const minutes = Math.floor(diff / 60000);
    return `${minutes}m ago`;
  };

  const isTraining = trainingStatus?.status === 'training' || syncProgress;

  return (
    <div>
      <Header locationText="SAP ERP Integration" onMenuToggle={onMenuToggle} />

      <div className="page-container">
        {/* Page Header */}
        <div className="page-banner" style={{ justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div className="page-banner-icon">
              <Database size={24} />
            </div>
            <div>
              <h1 className="page-banner-title" style={{ margin: 0 }}>SAP Sync & Retrain</h1>
              <p style={{ fontSize: 12, color: '#667085', margin: 0 }}>
                One-click sync data from SAP, retrain ML models, and generate fresh forecasts
              </p>
            </div>
          </div>
          <button className="btn-primary" onClick={() => testMut.mutate()} disabled={testMut.isPending}>
            {testMut.isPending ? 'Testing...' : 'Test Connection'}
          </button>
        </div>

        {/* Status KPIs */}
        <div className="kpi-grid" style={{ marginBottom: 24 }}>
          <div className="kpi-card">
            <div className="kpi-label">SAP Connection</div>
            <div className="kpi-value" style={{ fontSize: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
              {isConnected ? (
                <><CheckCircle size={20} color="var(--primary)" /> Connected</>
              ) : (
                <><XCircle size={20} color="var(--danger-text)" /> Offline</>
              )}
            </div>
            {mockStatus?.connected && (
              <div style={{ fontSize: 11, color: '#667085', marginTop: 4 }}>
                {mockStatus.materials_count} materials · {mockStatus.sales_orders} orders
              </div>
            )}
          </div>

          <div className="kpi-card">
            <div className="kpi-label">Last Training</div>
            <div className="kpi-value" style={{ fontSize: 18 }}>
              {lastTraining?.has_training ? formatTimeAgo(lastTraining.trained_at) : 'Never'}
            </div>
            {lastTraining?.has_training && (
              <div style={{ fontSize: 11, color: '#667085', marginTop: 4 }}>
                MAPE: {lastTraining.ensemble_mape}% · {lastTraining.models_trained}/6 models
              </div>
            )}
          </div>

          <div className="kpi-card">
            <div className="kpi-label">Forecast Status</div>
            <div className="kpi-value" style={{ fontSize: 18, display: 'flex', alignItems: 'center', gap: 8 }}>
              {lastTraining?.has_training ? (
                <><TrendingUp size={20} color="var(--primary)" /> Active</>
              ) : (
                <><AlertTriangle size={20} color="#b54708" /> No Forecasts</>
              )}
            </div>
            {lastTraining?.has_training && (
              <div style={{ fontSize: 11, color: '#667085', marginTop: 4 }}>
                {lastTraining.predictions_uploaded} predictions · {lastTraining.sku_count} SKUs
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

        {/* ═══ ONE BIG BUTTON ═══ */}
        <div style={{
          padding: '40px 32px', borderRadius: 16, border: '2px solid #eaecf0', backgroundColor: '#fff',
          boxShadow: '0 4px 16px rgba(0,0,0,0.06)', textAlign: 'center', marginBottom: 24,
        }}>
          {isTraining ? (
            <>
              <RefreshCw size={48} className="spin" color="#e9730c" style={{ marginBottom: 16 }} />
              <h2 style={{ fontSize: 22, fontWeight: 800, margin: '0 0 8px 0', color: '#b54708' }}>
                Training Models...
              </h2>
              <p style={{ fontSize: 14, color: '#667085', margin: '0 0 16px 0' }}>
                {syncProgress?.stage === 'starting' && 'Syncing SAP data, then training all 6 ML models...'}
                {trainingStatus?.status === 'training' && `Training ${trainingStatus.models_completed + 1}/6 models...`}
              </p>
              {trainingStatus && (
                <div style={{ maxWidth: 400, margin: '0 auto' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                    <span style={{ fontSize: 12, color: '#667085' }}>Progress</span>
                    <span style={{ fontSize: 12, fontWeight: 700, color: '#1a1d1a' }}>
                      {Math.round(((trainingStatus.models_completed || 0) / (trainingStatus.total_models || 6)) * 100)}%
                    </span>
                  </div>
                  <div style={{ height: 8, backgroundColor: '#f2f4f7', borderRadius: 4, overflow: 'hidden' }}>
                    <div style={{
                      height: '100%',
                      width: `${((trainingStatus.models_completed || 0) / (trainingStatus.total_models || 6)) * 100}%`,
                      backgroundColor: '#e9730c',
                      borderRadius: 4,
                      transition: 'width 0.5s ease',
                    }} />
                  </div>
                  <div style={{ display: 'flex', gap: 6, justifyContent: 'center', marginTop: 12, flexWrap: 'wrap' }}>
                    {['xgboost', 'lightgbm', 'arima', 'sarima', 'prophet', 'holt_winters'].map((model) => {
                      const info = trainingStatus.models?.[model];
                      const st = info?.status || 'pending';
                      return (
                        <span key={model} style={{
                          fontSize: 10, padding: '3px 8px', borderRadius: 4, fontFamily: 'monospace', fontWeight: 600,
                          backgroundColor: st === 'completed' ? '#ecfdf3' : st === 'failed' ? '#fef3f2' : st === 'training' ? '#fffaeb' : '#f2f4f7',
                          color: st === 'completed' ? '#027a48' : st === 'failed' ? '#dc2626' : st === 'training' ? '#b54708' : '#667085',
                          border: `1px solid ${st === 'completed' ? '#a6f4c5' : st === 'failed' ? '#fecdca' : st === 'training' ? '#fedf89' : '#eaecf0'}`,
                        }}>
                          {st === 'completed' && '✓ '}{st === 'failed' && '✗ '}{st === 'training' && '... '}{model}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
            </>
          ) : (
            <>
              <Cpu size={48} color="#667085" style={{ marginBottom: 16 }} />
              <h2 style={{ fontSize: 22, fontWeight: 800, margin: '0 0 8px 0', color: '#1a1d1a' }}>
                Sync & Retrain
              </h2>
              <p style={{ fontSize: 14, color: '#667085', margin: '0 0 24px 0', maxWidth: 500, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
                Syncs all data from SAP (materials, vendors, stocks, orders, sales),
                evaluates existing forecasts against new actuals, retrains all 6 ML models
                in parallel, and generates 12-week predictions for every SKU.
              </p>
              <button
                className="btn-primary"
                style={{
                  padding: '16px 56px', fontSize: 18, fontWeight: 800, borderRadius: 12,
                  display: 'inline-flex', alignItems: 'center', gap: 10,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.15)',
                }}
                onClick={() => retrainMut.mutate()}
                disabled={!isConnected}
              >
                <Play size={20} />
                Sync & Retrain All Models
              </button>
              {!isConnected && (
                <p style={{ fontSize: 12, color: '#dc2626', marginTop: 12 }}>
                  SAP connection required. Check connection status above.
                </p>
              )}
              <p style={{ fontSize: 11, color: '#667085', marginTop: 16 }}>
                Takes approximately 15-30 seconds. Safe to run multiple times — old predictions are replaced.
              </p>
            </>
          )}
        </div>

        {/* Result Message */}
        {resultMessage && (
          <div style={{
            padding: '14px 20px', borderRadius: 12, marginBottom: 20,
            backgroundColor: resultMessage.type === 'success' ? '#ecfdf3' : resultMessage.type === 'error' ? '#fef3f2' : '#eff8ff',
            border: `1px solid ${resultMessage.type === 'success' ? '#a6f4c5' : resultMessage.type === 'error' ? '#fecdca' : '#b4cff5'}`,
            display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              {resultMessage.type === 'success' && <BadgeCheck size={20} color="#027a48" style={{ marginTop: 2 }} />}
              {resultMessage.type === 'error' && <XCircle size={20} color="#dc2626" style={{ marginTop: 2 }} />}
              {resultMessage.type === 'info' && <CheckCircle size={20} color="#175cd3" style={{ marginTop: 2 }} />}
              <div>
                <div style={{ fontSize: 14, fontWeight: 700, color: resultMessage.type === 'success' ? '#027a48' : resultMessage.type === 'error' ? '#dc2626' : '#175cd3', marginBottom: 4 }}>
                  {resultMessage.title}
                </div>
                <div style={{ fontSize: 13, color: '#344054', lineHeight: 1.5 }}>
                  {resultMessage.text}
                </div>
              </div>
            </div>
            <button
              onClick={() => setResultMessage(null)}
              style={{
                padding: '4px 10px', borderRadius: 6, border: '1px solid #eaecf0',
                backgroundColor: '#fff', cursor: 'pointer', fontSize: 11, fontWeight: 600, color: '#667085',
                flexShrink: 0,
              }}
            >
              Dismiss
            </button>
          </div>
        )}

        {/* Training History */}
        {lastTraining?.has_training && (
          <div style={{
            borderRadius: 14, border: '1px solid #eaecf0', backgroundColor: '#fff',
            boxShadow: '0 2px 8px rgba(0,0,0,0.06)', marginBottom: 24, overflow: 'hidden',
          }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '14px 20px', borderBottom: '1px solid #eaecf0', backgroundColor: '#f9fafb',
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Clock size={16} color="#344054" />
                <span style={{ fontSize: 14, fontWeight: 700, color: '#1a1d1a' }}>Latest Training Run</span>
              </div>
              <span style={{ fontSize: 12, color: '#667085' }}>
                {new Date(lastTraining.trained_at).toLocaleString()}
              </span>
            </div>
            <div style={{ padding: '16px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 20, marginBottom: 16 }}>
                <div>
                  <div style={{ fontSize: 11, color: '#667085', marginBottom: 4 }}>Models Trained</div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: '#1a1d1a' }}>
                    {lastTraining.models_trained}<span style={{ fontSize: 14, fontWeight: 400, color: '#667085' }}>/6</span>
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#667085', marginBottom: 4 }}>Ensemble MAPE</div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: lastTraining.ensemble_mape < 10 ? '#027a48' : '#b54708' }}>
                    {lastTraining.ensemble_mape != null ? `${lastTraining.ensemble_mape}%` : 'N/A'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#667085', marginBottom: 4 }}>SKUs Covered</div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: '#1a1d1a' }}>
                    {lastTraining.sku_count || 'N/A'}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: 11, color: '#667085', marginBottom: 4 }}>Training Time</div>
                  <div style={{ fontSize: 20, fontWeight: 800, color: '#1a1d1a' }}>
                    {lastTraining.elapsed_seconds ? `${lastTraining.elapsed_seconds}s` : 'N/A'}
                  </div>
                </div>
              </div>

              {/* Per-model breakdown */}
              {lastTraining.per_model_metrics && (() => {
                try {
                  const perModel = JSON.parse(lastTraining.per_model_metrics);
                  return (
                    <div style={{ borderTop: '1px solid #f2f4f7', paddingTop: 12 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: '#344054', marginBottom: 8 }}>Model Breakdown</div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 8 }}>
                        {Object.entries(perModel).map(([name, info]) => (
                          <div key={name} style={{
                            padding: '8px 12px', borderRadius: 8,
                            border: `1px solid ${info.status === 'trained' ? '#a6f4c5' : '#fecdca'}`,
                            backgroundColor: info.status === 'trained' ? '#ecfdf3' : '#fef3f2',
                          }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                              <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'monospace' }}>{name}</span>
                              {info.status === 'trained' ? (
                                <Check size={12} color="#027a48" />
                              ) : (
                                <XCircle size={12} color="#dc2626" />
                              )}
                            </div>
                            {info.mape != null && (
                              <div style={{ fontSize: 11, color: '#667085' }}>MAPE: {info.mape}%</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                } catch {
                  return null;
                }
              })()}

              {/* Weights */}
              {lastTraining.weights && (() => {
                try {
                  const weights = JSON.parse(lastTraining.weights);
                  const sorted = Object.entries(weights).sort((a, b) => b[1] - a[1]);
                  return (
                    <div style={{ borderTop: '1px solid #f2f4f7', paddingTop: 12, marginTop: 12 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: '#344054', marginBottom: 8 }}>Ensemble Weights</div>
                      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                        {sorted.map(([name, weight]) => (
                          <div key={name} style={{
                            display: 'flex', alignItems: 'center', gap: 6, padding: '4px 10px',
                            borderRadius: 6, backgroundColor: '#f9fafb', border: '1px solid #eaecf0',
                          }}>
                            <span style={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 600 }}>{name}</span>
                            <span style={{ fontSize: 11, color: '#667085' }}>{(weight * 100).toFixed(1)}%</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                } catch {
                  return null;
                }
              })()}
            </div>
          </div>
        )}

        {/* No Training Yet */}
        {lastTraining && !lastTraining.has_training && !isTraining && (
          <div style={{
            padding: '16px 20px', borderRadius: 12, marginBottom: 20,
            backgroundColor: '#fffaeb', border: '1px solid #fedf89',
            display: 'flex', alignItems: 'center', gap: 12,
          }}>
            <AlertTriangle size={20} color="#b54708" />
            <div>
              <div style={{ fontSize: 14, fontWeight: 700, color: '#b54708' }}>No forecasts yet</div>
              <div style={{ fontSize: 13, color: '#92400e' }}>
                Click the "Sync & Retrain" button above to generate your first set of forecasts.
              </div>
            </div>
          </div>
        )}

        {/* Sync Operations Log */}
        <div className="card-table-container">
          <div className="table-card-header">
            <div className="table-card-title">Recent Sync Operations</div>
          </div>
          <table className="data-table">
            <thead>
              <tr>
                <th>Status</th>
                <th>Records Synced</th>
                <th>Modules</th>
                <th>Started</th>
                <th>Completed</th>
                <th>Error</th>
              </tr>
            </thead>
            <tbody>
              {(status?.recent_logs || []).length === 0 && (
                <tr>
                  <td colSpan={6} style={{ textAlign: 'center', padding: 30, color: '#667085' }}>
                    No operations yet. Click "Sync & Retrain" to get started.
                  </td>
                </tr>
              )}
              {(status?.recent_logs || []).map((log) => (
                <tr key={log.id}>
                  <td>
                    {log.status === 'completed' ? <span className="badge-pill badge-healthy">Completed</span> :
                     log.status === 'partial' ? <span className="badge-pill badge-low" style={{ backgroundColor: '#fef3f2', color: '#dc2626' }}>Partial</span> :
                     log.status === 'failed' ? <span className="badge-pill badge-low" style={{ backgroundColor: '#fef3f2', color: '#dc2626' }}>Failed</span> :
                     <span className="badge-pill badge-low">Running</span>}
                  </td>
                  <td style={{ fontWeight: 600 }}>{log.records_synced.toLocaleString()}</td>
                  <td style={{ fontSize: 11, color: '#667085' }}>
                    {(log.modules_synced || []).join(', ')}
                  </td>
                  <td style={{ color: '#667085', fontSize: 11 }}>
                    {log.started_at ? new Date(log.started_at).toLocaleString() : '—'}
                  </td>
                  <td style={{ color: '#667085', fontSize: 11 }}>
                    {log.completed_at ? new Date(log.completed_at).toLocaleString() : '—'}
                  </td>
                  <td style={{ color: '#d32f2f', fontSize: 11, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {log.error_message || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
