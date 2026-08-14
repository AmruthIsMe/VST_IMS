import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getSapSyncStatus, triggerSapSync, testSapConnection } from '../services/api';
import Header from '../components/Header';
import { Database, RefreshCw, CheckCircle, XCircle } from 'lucide-react';

const SYNC_TYPES = [
  { key: 'materials', label: 'Material Master', desc: 'SAP MARA/MARC tables' },
  { key: 'vendors', label: 'Vendor Master', desc: 'SAP LFA1/LFM1 tables' },
  { key: 'stocks', label: 'Inventory Stocks', desc: 'SAP MSEG/MKPF tables' },
  { key: 'orders', label: 'Purchase Orders', desc: 'SAP EKKO/EKPO tables' },
  { key: 'sales', label: 'Sales Orders', desc: 'SAP VBAK/VBAP tables' },
];

export default function SapSync() {
  const qc = useQueryClient();

  const { data: status } = useQuery({
    queryKey: ['sap-sync-status'],
    queryFn: () => getSapSyncStatus().then((r) => r.data),
    refetchInterval: 5000,
  });

  const syncMut = useMutation({
    mutationFn: (type) => triggerSapSync(type),
    onSuccess: () => qc.invalidateQueries(['sap-sync-status']),
  });

  const testMut = useMutation({
    mutationFn: () => testSapConnection(),
  });

  return (
    <div>
      <Header />

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

        <div className="kpi-grid" style={{ marginBottom: 24 }}>
          <div className="kpi-card">
            <div className="kpi-label">Connection Status</div>
            <div className="kpi-value" style={{ fontSize: 20, display: 'flex', alignItems: 'center', gap: 8 }}>
              {status?.connected ? (
                <><CheckCircle size={22} color="var(--primary)" /> Connected</>
              ) : (
                <><XCircle size={22} color="var(--danger-text)" /> Not Configured</>
              )}
            </div>
          </div>

          <div className="kpi-card">
            <div className="kpi-label">Last Sync</div>
            <div className="kpi-value" style={{ fontSize: 18 }}>
              {status?.last_sync ? new Date(status.last_sync).toLocaleString() : 'Never'}
            </div>
          </div>
        </div>

        <h2 style={{ fontSize: 18, fontWeight: 700, marginBottom: 16 }}>Sync Modules</h2>
        <div className="kpi-grid" style={{ gridTemplateColumns: 'repeat(3, 1fr)', marginBottom: 24 }}>
          {SYNC_TYPES.map(({ key, label, desc }) => (
            <div className="kpi-card" key={key}>
              <div style={{ fontWeight: 700, fontSize: 15, marginBottom: 4 }}>{label}</div>
              <div style={{ fontSize: 12, color: '#667085', marginBottom: 16 }}>{desc}</div>
              <button
                className="btn-primary"
                style={{ width: '100%', justifyContent: 'center' }}
                onClick={() => syncMut.mutate(key)}
                disabled={syncMut.isPending}
              >
                <RefreshCw size={14} className={syncMut.isPending ? 'spinning' : ''} />
                {syncMut.isPending ? 'Syncing...' : 'Sync Now'}
              </button>
            </div>
          ))}
        </div>

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
