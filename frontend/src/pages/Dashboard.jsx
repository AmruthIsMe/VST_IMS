import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getKPIs, getDemandTrend, getCategoryDistribution } from '../services/api';
import Header from '../components/Header';
import { AreaChart, Area, XAxis, YAxis, Tooltip, ResponsiveContainer, PieChart, Pie, Cell, Legend } from 'recharts';
import { DollarSign, Package, AlertTriangle, FileText, Search } from 'lucide-react';

const CATEGORY_COLORS = {
  'Spare Parts': '#1b365d',
  'Lubricants': '#0d7a42',
  'Electric Pumps': '#2b6cb0',
  'Engines': '#dd6b20',
  'Precision Comp.': '#805ad5',
  'Precision Components': '#805ad5',
};

export default function Dashboard() {
  const [search, setSearch] = useState('');
  const [catFilter, setCatFilter] = useState('All');
  const [statusFilter, setStatusFilter] = useState('All');
  const [critFilter, setCritFilter] = useState('All');

  const { data: kpis } = useQuery({ queryKey: ['kpis'], queryFn: () => getKPIs().then(r => r.data) });
  const { data: trend } = useQuery({ queryKey: ['demand-trend'], queryFn: () => getDemandTrend().then(r => r.data) });
  const { data: categories } = useQuery({ queryKey: ['category-dist'], queryFn: () => getCategoryDistribution().then(r => r.data) });

  // Format chart data for weekly demand trend area chart
  const trendData = (trend?.labels || []).map((label, idx) => ({
    name: label,
    value: trend.values[idx] || 5000,
  }));

  // Mock smooth curve data if database data is sparse
  const displayTrendData = trendData.length >= 5 ? trendData : [
    { name: 'Oct 06', value: 4840 },
    { name: 'Oct 20', value: 4890 },
    { name: 'Nov 03', value: 6220 },
    { name: 'Nov 17', value: 6480 },
    { name: 'Dec 01', value: 5880 },
    { name: 'Dec 15', value: 6000 },
    { name: 'Dec 29', value: 5990 },
  ];

  // Pie chart data
  const pieData = (categories?.labels || []).map((label, idx) => ({
    name: label === 'Precision Components' ? 'Precision Comp.' : label,
    value: categories.values[idx],
  }));

  const displayPieData = pieData.length > 0 ? pieData : [
    { name: 'Spare Parts', value: 52.6 },
    { name: 'Lubricants', value: 30.2 },
    { name: 'Electric Pumps', value: 12.0 },
    { name: 'Engines', value: 3.2 },
    { name: 'Precision Comp.', value: 2.0 },
  ];

  return (
    <div>
      <Header locationText="Malur Manufacturing Facility | Bengaluru, Karnataka" />

      <div className="page-container">
        {/* KPI Cards Row */}
        <div className="kpi-grid">
          {/* Card 1 */}
          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-green">
                <DollarSign size={22} />
              </div>
              <span className="kpi-badge kpi-badge-green">+4.2%</span>
            </div>
            <div>
              <div className="kpi-label">Total Inventory Value</div>
              <div className="kpi-value kpi-value-green">₹42,80,25,622</div>
              <div className="kpi-sub">Across all 5 categories</div>
            </div>
          </div>

          {/* Card 2 */}
          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-green">
                <Package size={22} />
              </div>
              <span className="kpi-badge kpi-badge-green">+2.1%</span>
            </div>
            <div>
              <div className="kpi-label">Total Units In Stock</div>
              <div className="kpi-value">58,255</div>
              <div className="kpi-sub">Current physical count</div>
            </div>
          </div>

          {/* Card 3 */}
          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-orange">
                <AlertTriangle size={22} />
              </div>
              <span className="kpi-badge kpi-badge-orange">+58 new</span>
            </div>
            <div>
              <div className="kpi-label">Critical Stock Alerts</div>
              <div className="kpi-value kpi-value-orange">60</div>
              <div className="kpi-sub">SKUs below reorder level</div>
            </div>
          </div>

          {/* Card 4 */}
          <div className="kpi-card">
            <div className="kpi-top-row">
              <div className="kpi-icon-box kpi-icon-blue">
                <FileText size={22} />
              </div>
              <span className="kpi-badge kpi-badge-green">87.9% Fill Rate</span>
            </div>
            <div>
              <div className="kpi-label">Unique SKUs Tracked</div>
              <div className="kpi-value">{kpis?.total_skus ?? 200}</div>
              <div className="kpi-sub">Active product lines</div>
            </div>
          </div>
        </div>

        {/* Charts Row */}
        <div className="charts-row">
          {/* Left Area Chart */}
          <div className="chart-card">
            <div className="chart-header">
              <div className="chart-title">
                <span className="chart-title-dot" style={{ backgroundColor: '#107c41' }}></span>
                Weekly Demand Trend
              </div>
              <div className="chart-filters">
                <select className="select-sm" defaultValue="Last 13 Weeks">
                  <option>Last 13 Weeks</option>
                  <option>Last 6 Months</option>
                  <option>Last 1 Year</option>
                </select>
                <input type="text" className="date-input-sm" defaultValue="09/29/2025" style={{ width: 95 }} />
                <input type="text" className="date-input-sm" defaultValue="12/29/2025" style={{ width: 95 }} />
                <button className="btn-apply">Apply</button>
              </div>
            </div>

            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={displayTrendData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorValue" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#107c41" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#107c41" stopOpacity={0.0} />
                  </linearGradient>
                </defs>
                <XAxis dataKey="name" tick={{ fontSize: 11, fill: '#667085' }} />
                <YAxis tick={{ fontSize: 11, fill: '#667085' }} domain={[4800, 6600]} />
                <Tooltip />
                <Area type="monotone" dataKey="value" stroke="#107c41" strokeWidth={2.5} fillOpacity={1} fill="url(#colorValue)" dot={{ r: 3, fill: '#107c41' }} />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Right Donut Chart */}
          <div className="chart-card">
            <div className="chart-header">
              <div className="chart-title">
                <span className="chart-title-dot" style={{ backgroundColor: '#1b365d' }}></span>
                Sales by Category
              </div>
            </div>

            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={displayPieData}
                  cx="50%"
                  cy="45%"
                  innerRadius={60}
                  outerRadius={90}
                  paddingAngle={2}
                  dataKey="value"
                  label={({ percent }) => `${(percent * 100).toFixed(1)}%`}
                  labelLine={false}
                >
                  {displayPieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={CATEGORY_COLORS[entry.name] || '#2b6cb0'} />
                  ))}
                </Pie>
                <Tooltip formatter={(val) => `${val}%`} />
                <Legend iconType="square" iconSize={10} wrapperStyle={{ fontSize: '11px', paddingTop: '10px' }} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Search & Filter Toolbar */}
        <div className="toolbar-card">
          <div className="toolbar-left">
            <div className="search-wrapper">
              <Search className="search-icon" size={16} />
              <input
                className="search-input"
                placeholder="Search by Name, SKU, or Machine Type..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="filter-group">
              <span>Category:</span>
              <select className="filter-select" value={catFilter} onChange={(e) => setCatFilter(e.target.value)}>
                <option value="All">All</option>
                <option value="Spare Parts">Spare Parts</option>
                <option value="Electric Pumps">Electric Pumps</option>
                <option value="Lubricants">Lubricants</option>
                <option value="Engines">Engines</option>
                <option value="Precision">Precision</option>
              </select>
            </div>

            <div className="filter-group">
              <span>Status:</span>
              <select className="filter-select" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="All">All</option>
                <option value="Healthy">Healthy</option>
                <option value="Low Stock">Low Stock</option>
                <option value="Critical">Critical</option>
                <option value="Out of Stock">Out of Stock</option>
              </select>
            </div>

            <div className="filter-group">
              <span>Criticality:</span>
              <select className="filter-select" value={critFilter} onChange={(e) => setCritFilter(e.target.value)}>
                <option value="All">All</option>
                <option value="High">High</option>
                <option value="Medium">Medium</option>
                <option value="Low">Low</option>
              </select>
            </div>
          </div>

          <div className="showing-count">
            Showing <strong>25</strong> of <strong>200</strong> SKUs
          </div>
        </div>
      </div>
    </div>
  );
}
