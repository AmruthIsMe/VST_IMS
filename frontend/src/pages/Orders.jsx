import { useState, useMemo } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getOrders, createOrder, updateOrder, deleteOrder } from '../services/api';
import Header from '../components/Header';
import { ShoppingCart, History, Clock, Truck, AlertCircle, Search, Plus, FileText, Pencil, Trash2, CheckCircle } from 'lucide-react';

const EMPTY = { order_id: '', order_date: new Date().toISOString().split('T')[0], customer_name: '', total_amount_inr: '50000', payment_status: 'Pending', order_status: 'Processing', items: [] };

function formatCurrency(amount) {
  if (amount == null) return '₹0';
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(amount);
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function mapOrder(o) {
  return {
    id: o.order_id,
    date: formatDate(o.order_date),
    client: o.customer_name,
    amt: formatCurrency(o.total_amount_inr),
    pay: o.payment_status,
    status: o.order_status,
    raw: o,
  };
}

export default function Orders() {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState('active');
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState('');
  const [payFilter, setPayFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [modal, setModal] = useState(null);
  const [form, setForm] = useState(EMPTY);

  const { data, isLoading } = useQuery({
    queryKey: ['orders', page, search, payFilter, statusFilter, activeTab],
    queryFn: () => {
      const status = activeTab === 'history' ? 'Delivered' : statusFilter;
      return getOrders({ page, page_size: 15, search, payment_status: payFilter, order_status: status }).then((r) => r.data);
    },
  });

  const createMut = useMutation({ mutationFn: createOrder, onSuccess: () => { qc.invalidateQueries(['orders']); setModal(null); } });
  const updateMut = useMutation({ mutationFn: ({ id, ...d }) => updateOrder(id, d), onSuccess: () => { qc.invalidateQueries(['orders']); setModal(null); } });
  const deleteMut = useMutation({ mutationFn: deleteOrder, onSuccess: () => qc.invalidateQueries(['orders']) });

  const openCreate = () => { setForm(EMPTY); setModal('create'); };
  const openEdit = (o) => { setForm({ ...o, order_date: o.order_date, id: o.id }); setModal('edit'); };
  const handleSubmit = (e) => { e.preventDefault(); modal === 'create' ? createMut.mutate(form) : updateMut.mutate(form); };

  const getPaymentBadge = (status) => {
    if (status === 'Paid') return <span className="badge-pill badge-paid">Paid</span>;
    if (status === 'Overdue') return <span className="badge-pill badge-overdue">Overdue</span>;
    return <span className="badge-pill badge-pending">Pending</span>;
  };

  const getOrderStatusBadge = (status) => {
    if (status === 'Shipped') return <span className="badge-pill badge-shipped">Shipped</span>;
    if (status === 'Delivered') return <span className="badge-pill badge-delivered">Delivered</span>;
    return <span className="badge-pill badge-processing">Processing</span>;
  };

  const ordersList = useMemo(() => (data?.items || []).map(mapOrder), [data]);

  const filteredOrders = ordersList;

  const kpiStats = useMemo(() => {
    const all = data?.items || [];
    const totalActive = all.filter(o => o.order_status !== 'Delivered').length;
    const processing = all.filter(o => o.order_status === 'Processing').length;
    const shipped = all.filter(o => o.order_status === 'Shipped').length;
    const overdue = all.filter(o => o.payment_status === 'Overdue').length;
    const delivered = all.filter(o => o.order_status === 'Delivered').length;
    const totalRevenue = all.filter(o => o.order_status === 'Delivered').reduce((s, o) => s + (o.total_amount_inr || 0), 0);
    const avgOrder = delivered > 0 ? totalRevenue / delivered : 0;
    return { totalActive, processing, shipped, overdue, delivered, totalRevenue, avgOrder };
  }, [data]);

  return (
    <div>
      <Header />

      <div className="page-container">
        {/* Page Banner Title */}
        <div className="page-banner">
          <div className="page-banner-icon">
            <ShoppingCart size={24} />
          </div>
          <h1 className="page-banner-title">Order Management</h1>
        </div>

        {/* Tabs */}
        <div className="page-tabs">
          <button
            className={`tab-btn ${activeTab === 'active' ? 'active' : ''}`}
            onClick={() => setActiveTab('active')}
          >
            <ShoppingCart size={16} /> Active Orders
          </button>
          <button
            className={`tab-btn ${activeTab === 'history' ? 'active' : ''}`}
            onClick={() => setActiveTab('history')}
          >
            <History size={16} /> Order History
          </button>
        </div>

        {/* KPI Cards - Different for Active vs History */}
        {activeTab === 'active' ? (
          <div className="kpi-grid">
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-blue">
                <ShoppingCart size={22} />
              </div>
              <div>
                <div className="kpi-label">Total Active</div>
                <div className="kpi-value">{kpiStats.totalActive}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-orange">
                <Clock size={22} />
              </div>
              <div>
                <div className="kpi-label">Processing</div>
                <div className="kpi-value kpi-value-orange">{kpiStats.processing}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-green">
                <Truck size={22} />
              </div>
              <div>
                <div className="kpi-label">Shipped</div>
                <div className="kpi-value kpi-value-green">{kpiStats.shipped}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-red">
                <AlertCircle size={22} />
              </div>
              <div>
                <div className="kpi-label">Overdue Payment</div>
                <div className="kpi-value kpi-value-red">{kpiStats.overdue}</div>
              </div>
            </div>
          </div>
        ) : (
          <div className="kpi-grid">
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-green">
                <CheckCircle size={22} />
              </div>
              <div>
                <div className="kpi-label">Total Delivered</div>
                <div className="kpi-value kpi-value-green">{kpiStats.delivered}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-blue">
                <FileText size={22} />
              </div>
              <div>
                <div className="kpi-label">Total Revenue</div>
                <div className="kpi-value">{formatCurrency(kpiStats.totalRevenue)}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-green">
                <Truck size={22} />
              </div>
              <div>
                <div className="kpi-label">Avg Order Value</div>
                <div className="kpi-value">{formatCurrency(kpiStats.avgOrder)}</div>
              </div>
            </div>
            <div className="kpi-card" style={{ flexDirection: 'row', alignItems: 'center', gap: 16 }}>
              <div className="kpi-icon-box kpi-icon-orange">
                <Clock size={22} />
              </div>
              <div>
                <div className="kpi-label">This Month</div>
                <div className="kpi-value kpi-value-orange">{kpiStats.totalActive}</div>
              </div>
            </div>
          </div>
        )}

        {/* Toolbar & Create Button */}
        <div className="toolbar-card">
          <div className="toolbar-left">
            <div className="search-wrapper">
              <Search className="search-icon" size={16} />
              <input
                className="search-input"
                placeholder="Search Order ID or Customer..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
              />
            </div>

            <select className="filter-select" value={payFilter} onChange={(e) => { setPayFilter(e.target.value); setPage(1); }}>
              <option value="">All Payment</option>
              <option value="Paid">Paid</option>
              <option value="Pending">Pending</option>
              <option value="Overdue">Overdue</option>
            </select>

            <select className="filter-select" value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}>
              <option value="">All Statuses</option>
              {activeTab === 'active' ? (
                <>
                  <option value="Processing">Processing</option>
                  <option value="Shipped">Shipped</option>
                </>
              ) : (
                <option value="Delivered">Delivered</option>
              )}
            </select>
          </div>

          <button className="btn-primary" onClick={openCreate}>
            <Plus size={18} /> Create New Order
          </button>
        </div>

        {/* Table Card */}
        <div className="card-table-container">
          <div className="table-card-header">
            <div className="table-card-title">{activeTab === 'active' ? 'Active Orders' : 'Order History'}</div>
            <div className="showing-count">
              Showing <strong>{filteredOrders.length}</strong> orders
            </div>
          </div>

          {isLoading ? <div className="loading">Loading orders...</div> : (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Order ID</th>
                  <th>Date & Time</th>
                  <th>Customer / Client</th>
                  <th>Total Amount</th>
                  <th>Payment Status</th>
                  <th>Order Status</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {filteredOrders.map((row, idx) => (
                  <tr key={row.id}>
                    <td style={{ fontWeight: 700, color: '#0284c7' }}>{row.id}</td>
                    <td style={{ color: '#64748b' }}>{row.date}</td>
                    <td style={{ fontWeight: 700, color: '#1e293b' }}>{row.client}</td>
                    <td style={{ fontWeight: 700 }}>{row.amt}</td>
                    <td>{getPaymentBadge(row.pay)}</td>
                    <td>{getOrderStatusBadge(row.status)}</td>
                    <td>
                      <div className="action-buttons">
                        <button className="act-btn act-invoice" onClick={() => alert(`Generating invoice for ${row.id}`)}>
                          <FileText size={13} /> Invoice
                        </button>
                        {activeTab === 'active' && (
                          <>
                            <button className="act-btn act-edit" onClick={() => openEdit(row)}>
                              <Pencil size={13} /> Edit
                            </button>
                            <button className="act-btn act-delete" onClick={() => { if (confirm('Delete?')) deleteMut.mutate(row.id); }}>
                              <Trash2 size={13} /> Delete
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {modal && (
        <div className="modal-overlay" onClick={() => setModal(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{modal === 'create' ? 'Create New Order' : 'Edit Order'}</h2>
            <form onSubmit={handleSubmit}>
              <div className="form-group"><label>Customer / Client</label><input value={form.customer_name || ''} onChange={(e) => setForm({ ...form, customer_name: e.target.value })} required /></div>
              <div className="form-group"><label>Total Amount (INR)</label><input type="number" value={form.total_amount_inr} onChange={(e) => setForm({ ...form, total_amount_inr: e.target.value })} required /></div>
              <div className="form-group"><label>Payment Status</label>
                <select value={form.payment_status} onChange={(e) => setForm({ ...form, payment_status: e.target.value })}>
                  <option value="Paid">Paid</option>
                  <option value="Pending">Pending</option>
                  <option value="Overdue">Overdue</option>
                </select>
              </div>
              <div className="form-group"><label>Order Status</label>
                <select value={form.order_status} onChange={(e) => setForm({ ...form, order_status: e.target.value })}>
                  <option value="Processing">Processing</option>
                  <option value="Shipped">Shipped</option>
                  <option value="Delivered">Delivered</option>
                </select>
              </div>
              <div className="modal-actions">
                <button type="button" className="btn-cancel" onClick={() => setModal(null)}>Cancel</button>
                <button type="submit" className="btn-primary">Save Order</button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
