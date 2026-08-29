import axios from 'axios';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api',
  headers: { 'Content-Type': 'application/json' },
});

// Attach token from localStorage if present
const savedToken = typeof window !== 'undefined' ? localStorage.getItem('vst_token') : null;
if (savedToken) {
  api.defaults.headers.common['Authorization'] = `Bearer ${savedToken}`;
}

// ─── Auth ───────────────────────────────────────────────────────────
export const loginApi = (username, password) => api.post('/auth/login', { username, password });
export const getMe = () => api.get('/auth/me');

// Dashboard
export const getKPIs = () => api.get('/dashboard/kpis');
export const getDemandTrend = (params) => api.get('/dashboard/charts/demand-trend', { params });
export const getCategoryDistribution = () => api.get('/dashboard/charts/category-distribution');
export const getSalesByRegion = () => api.get('/dashboard/charts/sales-by-region');
export const getStockoutRisk = (params) => api.get('/dashboard/stockout-risk', { params });
export const getCategoryForecast = () => api.get('/dashboard/charts/category-forecast');

// Products
export const getProducts = (params) => api.get('/products', { params });
export const getProduct = (id) => api.get(`/products/${id}`);
export const createProduct = (data) => api.post('/products', data);
export const updateProduct = (id, data) => api.put(`/products/${id}`, data);
export const deleteProduct = (id) => api.delete(`/products/${id}`);
export const getCategories = () => api.get('/products/categories');

// Suppliers
export const getSuppliers = (params) => api.get('/suppliers', { params });
export const getSupplier = (id) => api.get(`/suppliers/${id}`);
export const createSupplier = (data) => api.post('/suppliers', data);
export const updateSupplier = (id, data) => api.put(`/suppliers/${id}`, data);
export const deleteSupplier = (id) => api.delete(`/suppliers/${id}`);

// Orders
export const getOrders = (params) => api.get('/orders', { params });
export const getOrder = (id) => api.get(`/orders/${id}`);
export const getOrderItems = (id) => api.get(`/orders/${id}/items`);
export const getSapOrders = (params) => api.get('/orders/sap-orders', { params });
export const getStockMovements = (params) => api.get('/orders/stock-movements', { params });
export const createOrder = (data) => api.post('/orders', data);
export const updateOrder = (id, data) => api.put(`/orders/${id}`, data);
export const deleteOrder = (id) => api.delete(`/orders/${id}`);

// Users
export const getUsers = (params) => api.get('/users', { params });
export const getUser = (id) => api.get(`/users/${id}`);
export const createUser = (data) => api.post('/users', data);
export const updateUser = (id, data) => api.put(`/users/${id}`, data);
export const deleteUser = (id) => api.delete(`/users/${id}`);

// SAP
export const getSapSyncStatus = () => api.get('/sap/sync/status');
export const testSapConnection = () => api.post('/sap/test-connection');
export const checkSapMockStatus = () => api.get('/sap/mock-status');
export const syncSalesOnly = () => api.post('/sap/sync/sales');
export const syncAll = () =>
  api.post('/sap/sync-and-retrain?retrain=true', null, { timeout: 900000 });

// ─── Demand Forecasting ─────────────────────────────────────────────
export const trainForecastModels = (params) => api.post('/forecast/train', null, { params });
export const getForecastPredictions = (params) => api.get('/forecast/predict', { params });
export const compareForecastModels = (params) => api.get('/forecast/compare', { params });
export const getForecastMetrics = (params) => api.get('/forecast/metrics', { params });
export const getEnsembleWeights = () => api.get('/forecast/ensemble-weights');
export const retrainForecastModels = (params) => api.post('/forecast/retrain', null, { params });
export const listForecastModels = () => api.get('/forecast/models');
export const getForecastSummary = () => api.get('/forecast/summary');
export const getSkuExplorer = (params) => api.get('/forecast/sku-explorer', { params });
export const getYearlyDemand = (params) => api.get('/forecast/yearly-demand', { params });
export const getForecastProducts = (params) => api.get('/forecast/products', { params });
export const getReorderRecommendations = () => api.get('/forecast/reorder-recommendations');
export const getDriftMonitor = (params) => api.get('/forecast/drift-monitor', { params });
export const exportForecastCsv = (params) => api.get('/forecast/export-csv', { params, responseType: 'blob' });
export const getForecastCalendar = (params) => api.get('/forecast/calendar', { params });
export const compareForecastRuns = (params) => api.get('/forecast/compare-runs', { params });
export const getTrainingStatus = () => api.get('/forecast/training-status');
export const getTrainingHistory = (params) => api.get('/forecast/training-history', { params });

// ─── Genie Chatbot ──────────────────────────────────────────────────
export const sendGenieMessage = (message, conversationId) =>
  api.post('/genie/chat', { message, conversation_id: conversationId });
export const getGenieSuggestions = () => api.get('/genie/suggestions');
export const runWhatIf = (scenarioType, parameters) =>
  api.post('/genie/what-if', { scenario_type: scenarioType, parameters });
export const getGenieHistory = (conversationId) =>
  api.get(`/genie/history`, { params: { conversation_id: conversationId } });
export const getGenieCapabilities = () => api.get('/genie/capabilities');
export const exportGenieCsv = (reasoningTrace) =>
  api.post('/genie/export-csv', { reasoning_trace: reasoningTrace }, { responseType: 'blob' });

export default api;
