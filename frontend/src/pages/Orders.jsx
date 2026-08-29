import { useState, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getSapOrders, getStockMovements } from '../services/api';
import Header from '../components/Header';
import {
  ShoppingCart, History, Clock, Truck, AlertCircle, Search, Plus,
  FileText, ChevronDown, ChevronUp, Package, ArrowDownCircle,
  ArrowUpCircle, RotateCcw, Boxes,
} from 'lucide-react';

function formatCurrency(amount) {
  if (amount == null) return '₹0';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(amount);
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatDateTime(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

const STATUS_STYLES = {
  Completed: { bg: '#dcfce7', color: '#166534' },
  Shipped: { bg: '#dbeafe', color: '#1e40af' },
  Processing: { bg: '#fef3c7', color: '#92400e' },
  Dispatched: { bg: '#e0e7ff', color: '#3730a3' },
  Paid: { bg: '#dcfce7', color: '#166534' },
  Pending: { bg: '#fef3c7', color: '#92400e' },
  Overdue: { bg: '#fecaca', color: '#991b1b' },
};

function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || { bg: '#f1f5f9', color: '#475569' };
  return (
    <span style={{
      display: 'inline-block', padding: '2px 10px', borderRadius: 12,
      fontSize: 12, fontWeight: 600, background: s.bg, color: s.color,
    }}>{status}</span>
  );
}

function OrderItemsPanel({ items }) {
  if (!items || items.length === 0) {
    return <div style={{ padding: '12px 16px', color: '#94a3b8', fontStyle: 'italic' }}>No line items</div>;
  }
  return (
    <div style={{ padding: '0 16px 12px' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid #e2e8f0' }}>
            <th style={thStyle}>SKU</th>
            <th style={thStyle}>Category</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Qty</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Unit Price</th>
            <th style={{ ...thStyle, textAlign: 'right' }}>Total</th>
          </tr>
        </thead>
        <tbody>
          {items.map((it, i) => (
            <tr key={it.id || i} style={{ borderBottom: '1px solid #f1f5f9' }}>
              <td style={tdStyle}><span style={{ fontWeight: 700, color: '#0284c7' }}>{it.sku_id}</span></td>
              <td style={tdStyle}>{it.category}</td>
              <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 600 }}>{it.quantity}</td>
              <td style={{ ...tdStyle, textAlign: 'right' }}>{formatCurrency(it.unit_price_inr)}</td>
              <td style={{ ...tdStyle, textAlign: 'right', fontWeight: 700 }}>{formatCurrency(it.total_price_inr)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const thStyle = { textAlign: 'left', padding: '8px 4px', color: '#64748b', fontWeight: 600, fontSize: 12, textTransform: 'uppercase', letterSpacing: '0.5px' };
const tdStyle = { padding: '8px 4px', color: '#334155' };

export default function Orders({ onMenuToggle }) {
  const [activeTab, setActiveTab] = useState('sales');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [expandedRow, setExpandedRow] = useState(null);
  const [page, setPage] = useState(1);

  const { data: salesData, isLoading: salesLoading } = useQuery({
    queryKey: ['sap-orders', 'SALES_ORDER', page, search, statusFilter],
    queryFn: () => getSapOrders({
      page, page_size: 20, order_type: 'SALES_ORDER', search, order_status: statusFilter,
    }).then(r => r.data),
    enabled: activeTab === 'sales',
  });

  const { data: poData, isLoading: poLoading } = useQuery({
    queryKey: ['sap-orders', 'PURCHASE_ORDER', page, search, statusFilter],
    queryFn: () => getSapOrders({
      page, page_size: 20, order_type: 'PURCHASE_ORDER', search, order_status: statusFilter,
    }).then(r => r.data),
    enabled: activeTab === 'purchase',
  });

  const { data: movementData, isLoading: movementLoading } = useQuery({
    queryKey: ['stock-movements'],
    queryFn: () => getStockMovements({ limit: 200 }).then(r => r.data),
    enabled: activeTab === 'movements',
  });

  const orders = activeTab === 'sales' ? (salesData?.items || []) :
                 activeTab === 'purchase' ? (poData?.items || []) : [];
  const total = activeTab === 'sales' ? (salesData?.total || 0) :
                activeTab === 'purchase' ? (poData?.total || 0) : 0;
  const isLoading = activeTab === 'sales' ? salesLoading :
                    activeTab === 'purchase' ? poLoading : movementLoading;
  const movements = movementData?.movements || [];

  const kpis = useMemo(() => {
    if (activeTab === 'movements') {
      const inbound = movements.filter(m => m.direction === 'IN').length;
      const outbound = movements.filter(m => m.direction === 'OUT').length;
      const totalQtyIn = movements.filter(m => m.direction === 'IN').reduce((s, m) => s + m.quantity, 0);
      const totalQtyOut = movements.filter(m => m.direction === 'OUT').reduce((s, m) => s + m.quantity, 0);
      return { inbound, outbound, totalQtyIn, totalQtyOut };
    }
    const items = orders;
    return {
      totalOrders: total,
      completed: items.filter(o => o.order_status === 'Completed').length,
      inTransit: items.filter(o => o.order_status === 'Shipped').length,
      processing: items.filter(o => o.order_status === 'Processing').length,
      totalValue: items.reduce((s, o) => s + (o.total_amount_inr || 0), 0),
    };
  }, [orders, movements, total, activeTab]);

  const toggleExpand = (id) => {
    setExpandedRow(expandedRow === id ? null : id);
  };

  return (
    <div>
      <Header onMenuToggle={onMenuToggle} />
      <div className="page-container">
        <div className="page-banner">
          <div className="page-banner-icon"><Boxes size={24} /></div>
          <h1 className="page-banner-title">Order Management</h1>
        </div>

        {/* Tabs */}
        <div className="page-tabs">
          <button className={`tab-btn ${activeTab === 'sales' ? 'active' : ''}`}
            onClick={() => { setActiveTab('sales'); setPage(1); setSearch(''); setStatusFilter(''); setExpandedRow(null); }}>
            <ShoppingCart size={16} /> Sales Orders
          </button>
          <button className={`tab-btn ${activeTab === 'purchase' ? 'active' : ''}`}
            onClick={() => { setActiveTab('purchase'); setPage(1); setSearch(''); setStatusFilter(''); setExpandedRow(null); }}>
            <Package size={16} /> Purchase Orders
          </button>
          <button className={`tab-btn ${activeTab === 'movements' ? 'active' : ''}`}
            onClick={() => { setActiveTab('movements'); setExpandedRow(null); }}>
            <RotateCcw size={16} /> Stock Movements
          </button>
        </div>

        {/* KPI Cards */}
        {activeTab === 'movements' ? (
          <div className="kpi-grid">
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-green"><ArrowDownCircle size={22} /></div>
              <div>
                <div className="kpi-label">Inbound (Receipts)</div>
                <div className="kpi-value kpi-value-green">{kpis.inbound}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-red"><ArrowUpCircle size={22} /></div>
              <div>
                <div className="kpi-label">Outbound (Dispatches)</div>
                <div className="kpi-value kpi-value-red">{kpis.outbound}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-blue"><ArrowDownCircle size={22} /></div>
              <div>
                <div className="kpi-label">Total Units Received</div>
                <div className="kpi-value">{kpis.totalQtyIn.toLocaleString()}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-orange"><ArrowUpCircle size={22} /></div>
              <div>
                <div className="kpi-label">Total Units Dispatched</div>
                <div className="kpi-value kpi-value-orange">{kpis.totalQtyOut.toLocaleString()}</div>
              </div>
            </div>
          </div>
        ) : (
          <div className="kpi-grid">
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-blue">
                {activeTab === 'sales' ? <ShoppingCart size={22} /> : <Package size={22} />}
              </div>
              <div>
                <div className="kpi-label">Total {activeTab === 'sales' ? 'Sales' : 'Purchase'} Orders</div>
                <div className="kpi-value">{kpis.totalOrders}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-green"><FileText size={22} /></div>
              <div>
                <div className="kpi-label">Completed</div>
                <div className="kpi-value kpi-value-green">{kpis.completed}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-orange"><Truck size={22} /></div>
              <div>
                <div className="kpi-label">In Transit</div>
                <div className="kpi-value kpi-value-orange">{kpis.inTransit}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-blue"><FileText size={22} /></div>
              <div>
                <div className="kpi-label">Total Value</div>
                <div className="kpi-value">{formatCurrency(kpis.totalValue)}</div>
              </div>
            </div>
          </div>
        )}

        {/* Toolbar */}
        {activeTab !== 'movements' && (
          <div className="toolbar-card">
            <div className="toolbar-left">
              <div className="search-wrapper">
                <Search className="search-icon" size={16} />
                <input className="search-input"
                  placeholder="Search order ID, customer, supplier..."
                  value={search}
                  onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                />
              </div>
              <select className="filter-select" value={statusFilter}
                onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
                <option value="">All Statuses</option>
                <option value="Processing">Processing</option>
                <option value="Shipped">Shipped</option>
                <option value="Completed">Completed</option>
              </select>
            </div>
          </div>
        )}

        {/* Content */}
        {activeTab !== 'movements' ? (
          <div className="card-table-container">
            <div className="table-card-header">
              <div className="table-card-title">
                {activeTab === 'sales' ? 'Sales Orders (Outgoing)' : 'Purchase Orders (Incoming)'}
              </div>
              <div className="showing-count">
                Showing <strong>{orders.length}</strong> of {total} orders
              </div>
            </div>

            {isLoading ? <div className="loading">Loading orders...</div> : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th style={{ width: 30 }}></th>
                    <th>{activeTab === 'sales' ? 'Order ID' : 'PO Number'}</th>
                    <th>Date</th>
                    <th>{activeTab === 'sales' ? 'Customer' : 'Supplier'}</th>
                    <th>Items</th>
                    <th>Total Amount</th>
                    <th>Payment</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((row) => {
                    const isExpanded = expandedRow === row.id;
                    const partyName = activeTab === 'sales' ? row.customer_name : row.supplier_name;
                    return (
                      <>
                        <tr key={row.id} style={{ cursor: 'pointer' }}
                          onClick={() => toggleExpand(row.id)}>
                          <td>
                            {isExpanded ? <ChevronUp size={16} color="#64748b" /> :
                             <ChevronDown size={16} color="#64748b" />}
                          </td>
                          <td style={{ fontWeight: 700, color: '#0284c7' }}>{row.order_id}</td>
                          <td style={{ color: '#64748b' }}>{formatDate(row.order_date)}</td>
                          <td style={{ fontWeight: 600, color: '#1e293b' }}>{partyName || '—'}</td>
                          <td>
                            <span style={{
                              display: 'inline-flex', alignItems: 'center', gap: 4,
                              padding: '2px 8px', borderRadius: 8, fontSize: 12,
                              background: '#f1f5f9', color: '#475569', fontWeight: 600,
                            }}>
                              <Boxes size={12} /> {row.item_count}
                            </span>
                          </td>
                          <td style={{ fontWeight: 700 }}>{formatCurrency(row.total_amount_inr)}</td>
                          <td><StatusBadge status={row.payment_status} /></td>
                          <td><StatusBadge status={row.order_status} /></td>
                        </tr>
                        {isExpanded && (
                          <tr key={`${row.id}-detail`}>
                            <td colSpan={8} style={{ padding: 0, background: '#f8fafc' }}>
                              <div style={{ padding: '12px 16px', borderBottom: '1px solid #e2e8f0' }}>
                                <div style={{ display: 'flex', gap: 24, fontSize: 13, color: '#64748b' }}>
                                  <span><strong>Type:</strong> {row.order_type === 'SALES_ORDER' ? 'Sales Order (Outgoing)' : 'Purchase Order (Incoming)'}</span>
                                  {row.sap_po_number && <span><strong>SAP Ref:</strong> {row.sap_po_number}</span>}
                                  {row.fulfillment_region && <span><strong>Region:</strong> {row.fulfillment_region}</span>}
                                  <span><strong>Created:</strong> {formatDateTime(row.created_at)}</span>
                                </div>
                              </div>
                              <OrderItemsPanel items={row.items} />
                            </td>
                          </tr>
                        )}
                      </>
                    );
                  })}
                  {orders.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                        No orders found. Run a SAP Sync to pull order data.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        ) : (
          /* Stock Movements Tab */
          <div className="card-table-container">
            <div className="table-card-header">
              <div className="table-card-title">Stock Movements Ledger</div>
              <div className="showing-count">
                Showing <strong>{movements.length}</strong> movements
              </div>
            </div>

            {isLoading ? <div className="loading">Loading movements...</div> : (
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>SKU</th>
                    <th>Direction</th>
                    <th>Type</th>
                    <th>Order Ref</th>
                    <th>Date</th>
                    <th>Qty</th>
                    <th>Stock After</th>
                  </tr>
                </thead>
                <tbody>
                  {movements.slice().reverse().map((m) => (
                    <tr key={m.id}>
                      <td style={{ color: '#64748b', fontSize: 12 }}>{formatDateTime(m.timestamp)}</td>
                      <td style={{ fontWeight: 700, color: '#0284c7' }}>{m.matnr}</td>
                      <td>
                        {m.direction === 'IN' ? (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#16a34a', fontWeight: 700, fontSize: 13 }}>
                            <ArrowDownCircle size={14} /> IN
                          </span>
                        ) : (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, color: '#dc2626', fontWeight: 700, fontSize: 13 }}>
                            <ArrowUpCircle size={14} /> OUT
                          </span>
                        )}
                      </td>
                      <td>
                        <StatusBadge status={m.movement_type === 'goods_receipt' ? 'Completed' : 'Shipped'} />
                        <span style={{ marginLeft: 6, fontSize: 11, color: '#94a3b8' }}>
                          {m.movement_type === 'goods_receipt' ? 'Receipt' : 'Dispatch'}
                        </span>
                      </td>
                      <td style={{ fontWeight: 600, color: '#475569' }}>{m.order_id}</td>
                      <td style={{ color: '#64748b' }}>{formatDate(m.order_date)}</td>
                      <td style={{ fontWeight: 700, color: m.direction === 'IN' ? '#16a34a' : '#dc2626' }}>
                        {m.direction === 'IN' ? '+' : '-'}{m.quantity}
                      </td>
                      <td style={{ fontWeight: 600 }}>{m.stock_after.toLocaleString()}</td>
                    </tr>
                  ))}
                  {movements.length === 0 && (
                    <tr>
                      <td colSpan={8} style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
                        No stock movements yet. Run a SAP Sync to generate order data.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
