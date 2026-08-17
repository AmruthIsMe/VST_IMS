# VST IMS — Project Documentation

> **VST Tillers & Tractors Limited** — Malur Manufacturing Facility, Karnataka, India
> RL-Driven Demand Forecasting and Inventory Management System with AI Chatbot

---

## Table of Contents

1. [Project Overview](#1-project-overview)
2. [Tech Stack](#2-tech-stack)
3. [Database Schema](#3-database-schema)
4. [Dashboard Module](#4-dashboard-module)
5. [Products Module](#5-products-module)
6. [Suppliers Module](#6-suppliers-module)
7. [Orders Module](#7-orders-module)
8. [Users Module](#8-users-module)
9. [SAP Integration](#9-sap-integration)
10. [Demand Forecasting Engine](#10-demand-forecasting-engine)
11. [RL Feedback Loop](#11-rl-feedback-loop)
12. [Genie AI Chatbot](#12-genie-ai-chatbot)
13. [Frontend Application](#13-frontend-application)
14. [API Endpoints Reference](#14-api-endpoints-reference)
15. [Project File Structure](#15-project-file-structure)
16. [Getting Started](#16-getting-started)

---

## 1. Project Overview

VST IMS is a comprehensive inventory management system built for VST Tillers & Tractors Limited, an Indian agricultural machinery manufacturer. The system combines traditional CRUD operations with advanced demand forecasting and an AI-powered chatbot to provide actionable supply-chain intelligence.

### Business Domain

- **Company**: VST Tillers & Tractors Limited (est. 1967, JV with Mitsubishi Heavy Industries)
- **Products**: Power tillers, compact tractors, diesel engines, electric pumps, spare parts, lubricants, precision components
- **Supply Chain**: 4 geographies — Japan (45-90d lead), China (30-75d, highest volatility), Germany (60-120d), India domestic (7-30d)
- **Seasonality**: Kharif (Jun-Oct), Rabi (Nov-Mar), Monsoon (Jun-Sep), Post-harvest (Nov-Dec), Pre-monsoon buying (Apr-May)
- **Scale**: 200 SKUs across 5 categories, 28 suppliers, 41,800+ weekly sales records (2022-2025)

### Core Capabilities

| Capability | Description |
|---|---|
| Inventory Management | CRUD for products, suppliers, orders, users with search, filter, pagination |
| Demand Forecasting | 6-model ML ensemble (XGBoost, LightGBM, ARIMA, SARIMA, Prophet, Holt-Winters) with adaptive weighting |
| RL Feedback Loop | Multi-armed bandit (UCB1) optimizes ensemble weights based on prediction errors |
| SKU Explorer | Per-SKU 12-week forecast with ±2σ confidence bands, trend analysis, stockout alerts |
| Reorder Engine | Automated recommendations: which SKUs, how much, by when, estimated cost |
| Drift Monitor | Actuals vs Forecast tracking with weekly MAPE and bias degradation alerts |
| SAP Integration | Pluggable RFC (ECC 6.0) and OData (S/4HANA) connectors for Materials, Vendors, Stocks, Orders, Sales |
| AI Chatbot (Genie) | Multi-agent NL interface combining SQL queries, forecast data, and what-if simulations |
| Dashboard | 6 KPIs, demand trend charts, category distribution, 12-week forecast cards, stockout risk table |

---

## 2. Tech Stack

### Backend

| Component | Technology |
|---|---|
| Framework | FastAPI (Python) |
| ORM | SQLAlchemy 2.0 with Alembic migrations |
| Database | SQLite (local dev) / PostgreSQL 16 (Docker) |
| Auth | python-jose (JWT) + passlib (bcrypt) |
| ML/Forecasting | XGBoost, LightGBM, ARIMA, SARIMA, Prophet, Holt-Winters |
| Data Science | pandas, numpy, scipy, scikit-learn, joblib |
| LLM | Google Generative AI — Gemini 2.5 Flash |
| SAP | pyrfc (RFC) / httpx (OData) |
| Config | pydantic-settings, python-dotenv |

### Frontend

| Component | Technology |
|---|---|
| Framework | React 19 with Vite 8 |
| Routing | react-router-dom 7 |
| State/Data | @tanstack/react-query 5, React Context |
| Tables | @tanstack/react-table 9 |
| Charts | Recharts 3 |
| HTTP Client | Axios |
| Icons | Lucide React |
| Linting | oxlint |

### Infrastructure

| Component | Technology |
|---|---|
| Containerization | Docker Compose (3 services: db, backend, frontend) |
| Database (Docker) | PostgreSQL 16 |
| Local Dev | SQLite, uvicorn --reload |

---

## 3. Database Schema

12 tables managing the full inventory lifecycle:

| Table | Rows | Purpose |
|---|---|---|
| `products` | 200 | SKU catalog. Fields: sku_id, category, sub_category, machine_compatibility, shelf_life_days, criticality_score (1-5), sap_material_id |
| `suppliers` | 28 | Vendor directory. Fields: supplier_id, origin_country, primary_category, base_lead_time_days, lead_time_volatility, moq, unit_cost_inr |
| `users` | 5 | System users with roles (Admin, Manager, Viewer) |
| `orders` | 5 | Purchase orders. Fields: order_id, order_date, customer_name, total_amount_inr, payment_status, order_status |
| `order_items` | 0 | Line items per order. FK to orders and products |
| `sales` | 41,800 | Weekly sales history (2022-2025). Fields: sale_date, product_id, sku_id, units_sold, fulfillment_region, stockout_flag |
| `external_factors` | 209 | Macroeconomic/climate data. Fields: factor_date, monsoon_index, crop_sowing_season, macro_economic_index |
| `forecasts` | 10,200 | Ensemble forecast output per SKU per week. Fields: predicted_demand, actual_demand, model_version |
| `forecast_models` | 0 | Model registry. Fields: model_name, model_type, mae, mape, rmse, smape, bias, ensemble_weight |
| `forecast_predictions` | 0 | Per-model predictions with confidence intervals. Fields: lower_bound, upper_bound |
| `sap_sync_log` | — | SAP sync audit trail. Fields: sync_type, status, records_synced, error_message |
| `sap_config` | — | SAP connection settings. Fields: host, system_number, client, user, password_encrypted |

### Product Categories

| Prefix | Category | SKU Count | Criticality |
|---|---|---|---|
| SP- | Spare Parts | 80 | High — stockout directly impacts customer service |
| LU- | Lubricants | 30 | Medium — regular consumption, predictable |
| EP- | Electric Pumps | 40 | Very High — missed monsoon = lost year of sales |
| EN- | Engines | 20 | High — long lead time from Japan, expensive per unit |
| PC- | Precision Components | 30 | Very High — single-source from Germany/Japan |

---

## 4. Dashboard Module

**Prefix:** `/api/dashboard` — **6 endpoints**

| Endpoint | Description |
|---|---|
| `GET /kpis` | 6 KPI cards: total_skus, total_suppliers, active_orders, total_sales, low_stock_count, fill_rate |
| `GET /charts/demand-trend` | Demand trend with date range filtering and daily/weekly/monthly granularity |
| `GET /charts/category-distribution` | Pie chart data — product count per category |
| `GET /charts/sales-by-region` | Sales aggregated by fulfillment region |
| `GET /charts/category-forecast` | 12-week category-level forecast with trend arrows and contribution % |
| `GET /stockout-risk` | Per-SKU stockout risk analysis with EWMA trend, coverage weeks, risk levels (CRITICAL/HIGH/MEDIUM/LOW) |

**Frontend:** `Dashboard.jsx` — 4 KPI cards, demand trend area chart, pie chart, 12-week forecast cards, stockout risk table with search/filter/pagination for all 200 SKUs.

---

## 5. Products Module

**Prefix:** `/api/products` — **6 endpoints**

Full CRUD with paginated list, search by SKU/name/category, category filter, and sorting. Validates unique sku_id on create.

| Endpoint | Method | Description |
|---|---|---|
| `/api/products` | GET | Paginated list with search, category filter, sorting |
| `/api/products/categories` | GET | List categories with SKU counts |
| `/api/products/{id}` | GET | Get single product |
| `/api/products` | POST | Create product (validates unique sku_id) |
| `/api/products/{id}` | PUT | Update product |
| `/api/products/{id}` | DELETE | Delete product |

---

## 6. Suppliers Module

**Prefix:** `/api/suppliers` — **5 endpoints**

CRUD with paginated list, search by name/country/category. Supports 4 origin countries: Japan, China, Germany, India.

| Endpoint | Method | Description |
|---|---|---|
| `/api/suppliers` | GET | Paginated list with search and category filter |
| `/api/suppliers/{id}` | GET | Get single supplier |
| `/api/suppliers` | POST | Create supplier |
| `/api/suppliers/{id}` | PUT | Update supplier |
| `/api/suppliers/{id}` | DELETE | Delete supplier |

---

## 7. Orders Module

**Prefix:** `/api/orders` — **5 endpoints**

CRUD with eager-loaded order items. Supports payment_status (Pending/Paid/Overdue) and order_status (Created/Confirmed/Shipped/Delivered/Cancelled) filters.

| Endpoint | Method | Description |
|---|---|---|
| `/api/orders` | GET | Paginated list with search, status filters. Eager-loads order items |
| `/api/orders/{id}` | GET | Get single order with items |
| `/api/orders` | POST | Create order with line items (auto-calculates total_price_inr) |
| `/api/orders/{id}` | PUT | Update order |
| `/api/orders/{id}` | DELETE | Delete order |

---

## 8. Users Module

**Prefix:** `/api/users` — **5 endpoints**

CRUD with role-based access. Passwords are hashed with bcrypt on create/update.

| Endpoint | Method | Description |
|---|---|---|
| `/api/users` | GET | Paginated list with search, role, status filters |
| `/api/users/{id}` | GET | Get single user |
| `/api/users` | POST | Create user (hashes password) |
| `/api/users/{id}` | PUT | Update user |
| `/api/users/{id}` | DELETE | Delete user |

---

## 9. SAP Integration

**Prefix:** `/api/sap` — **4 endpoints**

Pluggable SAP connector supporting both legacy RFC (ECC 6.0) and modern OData (S/4HANA) protocols. Auto-detects based on config host.

| Endpoint | Method | Description |
|---|---|---|
| `/api/sap/sync-status` | GET | Connection status, last sync time, recent sync logs |
| `/api/sap/config` | POST | Save/update SAP connection config |
| `/api/sap/test-connection` | POST | Test SAP connectivity |
| `/api/sap/sync` | POST | Trigger sync for: materials, vendors, stocks, orders, sales |

### Sync Entities

| Entity | SAP Table | Direction |
|---|---|---|
| Materials | MARA | SAP → IMS |
| Vendors | LFA1 | SAP → IMS |
| Stocks | MSEG/MKPF | SAP → IMS |
| Orders | EKKO/EKPO | SAP → IMS |
| Sales | VBAK/VBAP | SAP → IMS |

---

## 10. Demand Forecasting Engine

**Prefix:** `/api/forecast` — **14 endpoints**

The forecasting engine is the core ML component of the system. It trains 6 models, computes adaptive ensemble weights via inverse-MAPE weighting, and generates predictions with confidence intervals.

### 6 Forecasting Models

| Model | Type | Strengths |
|---|---|---|
| XGBoost | Gradient Boosting | Handles non-linear patterns and feature interactions. Excellent for structured data |
| LightGBM | Gradient Boosting | Fast, handles categorical features natively with leaf-wise growth |
| ARIMA | Time Series | Models trend and autocorrelation. Best for stationary series |
| SARIMA | Seasonal ARIMA | Extends ARIMA with seasonal components. Ideal for monsoon/harvest cycles |
| Prophet | Additive Model | Robust to missing data, handles holidays and changepoints |
| Holt-Winters | Exponential Smoothing | Adaptive smoothing with trend and seasonal decomposition |

### Feature Engineering

The data pipeline creates 30+ features per SKU per week:

- **Lag features**: 1w, 2w, 4w, 8w, 13w, 26w, 52w
- **Rolling statistics**: mean, std, min, max for 4w, 13w, 26w windows
- **Calendar features**: week_of_year, month, quarter, day_of_year
- **Seasonal flags**: is_kharif, is_rabi, is_monsoon, is_post_harvest, is_pre_monsoon
- **Cyclical encoding**: sin/cos for week and month
- **Trend features**: YoY change, weeks_since_start
- **External factors**: monsoon_index, crop_sowing_season, macro_economic_index

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/forecast/train` | POST | Train all 6 models with optional SKU/category filter |
| `/api/forecast/predict` | GET | Get ensemble or model-specific predictions with horizon |
| `/api/forecast/compare` | GET | Compare all models side-by-side on test data |
| `/api/forecast/metrics` | GET | Detailed error metrics per model (MAE, MAPE, RMSE, SMAPE, Bias) |
| `/api/forecast/ensemble-weights` | GET | Current weights, weight history, RL diagnostics |
| `/api/forecast/retrain` | POST | Retrain with RL feedback loop (70% ensemble + 30% RL weights) |
| `/api/forecast/models` | GET | List all 6 models with status, weight, description |
| `/api/forecast/summary` | GET | AI-generated summary of ensemble performance |
| `/api/forecast/products` | GET | Product catalog with filtering for SKU Explorer |
| `/api/forecast/sku-explorer` | GET | Per-SKU 12-week forecast with ±2σ confidence band, stockout alert |
| `/api/forecast/reorder-recommendations` | GET | Which SKUs to order, how much, by when, estimated cost |
| `/api/forecast/drift-monitor` | GET | Actuals vs Forecast drift with weekly MAPE and bias tracking |
| `/api/forecast/export-csv` | GET | Export full 200-SKU forecast table as CSV |
| `/api/forecast/calendar` | GET | Forecast calendar with per-week predicted demand and low-stock warnings |

---

## 11. RL Feedback Loop

The RL feedback loop uses a multi-armed bandit (UCB1 algorithm) to dynamically optimize ensemble model weights based on real-world prediction performance.

### How It Works

1. Each model is a "bandit arm" with a reward history
2. Reward = negative normalized absolute prediction error (lower error = higher reward)
3. UCB1 balances exploration (trying underperforming models) vs exploitation (using the best)
4. Exponential decay emphasizes recent performance over historical
5. Updated weights are blended 70% ensemble + 30% RL on retrain

### Metrics Tracked

- **Per-model rewards**: Cumulative, count, average
- **UCB1 scores**: Confidence bounds for each arm
- **Weight evolution**: History of weight changes over time
- **Retrain suggestions**: Which models to retrain based on drift

---

## 12. Genie AI Chatbot

**Prefix:** `/api/genie` — **6 endpoints**

Genie is the AI-powered inventory intelligence assistant. It combines natural language understanding with live database queries, demand forecasts, and supply-chain simulations to provide actionable advice in plain English.

### Architecture

Genie uses a **multi-agent architecture** orchestrated by a planner LLM:

```
User Message
  → Input Guardrails (prompt injection, off-topic, PII)
  → Planner LLM (decides which agents to invoke)
  → Agent Execution (SQL Agent / Stock Advisor / What-If Agent)
  → Response Synthesis (LLM merges results into markdown)
  → Output Guardrails (PII redaction)
  → Confidence Classification
  → Return with Reasoning Trace
```

### The Three Agents

#### Expert A — SQL Agent (`sql_agent.py`)

Translates natural-language questions into read-only SQL queries using Gemini with a live schema DDL extracted from SQLAlchemy ORM models.

- **Input**: "How many SKUs are there per category?"
- **Process**: Gemini generates SELECT-only SQL against live DB schema → executes → returns rows
- **Safety**: SQL guardrails reject any non-SELECT statement (INSERT/UPDATE/DELETE/DROP blocked). SQLite-compatible syntax enforced. Self-correction retry on syntax errors.
- **Fallback**: Deterministic SQL builder for canonical questions when Gemini is unavailable

#### Expert B — Stock Advisor Agent (`stock_advisor_agent.py`)

The core "do the math" agent. Combines current inventory reality with future demand predictions to produce reorder recommendations.

- **Input**: "Do we need to order more Spare Parts for December?"
- **Process**:
  1. **Expert A (current stock)**: Queries sales history for burn rate (avg weekly demand over 13 weeks) and estimated stock (burn rate × 8 weeks coverage)
  2. **Expert B (projected demand)**: Queries ensemble forecasts table; falls back to EWMA trend projection (last 4w avg × trend ratio × weeks in month)
  3. **Math**: shortfall = projected demand − estimated stock → reorder qty
  4. **Synthesis**: Gemini produces a markdown response with tables, urgency tags, and recommendations
- **Safety**: Adapts to datasets with historical data (finds max sale_date, queries relative to it)

#### What-If Agent (`what_if_agent.py`)

Routes scenario questions to the appropriate simulator method.

| Scenario | Example Question | What It Simulates |
|---|---|---|
| Lead Time | "What if lead time from China increases by 15 days?" | Which SKUs run short when replenishment takes longer |
| Demand Spike | "What if demand for Spare Parts spikes by 25%?" | Which SKUs can't handle a demand surge |
| Shelf Life | "Which items are at risk of expiring?" | Items with shelf life below threshold |
| Supplier Failure | "What if a Japan supplier fails for 8 weeks?" | Stockout runway when a supplier goes down |

### Safety Guardrails (`guardrails.py`)

| Layer | What It Does |
|---|---|
| Prompt Injection | 12 regex patterns detect instruction override attempts |
| Off-Topic Blocking | Blocks questions about politics, religion, salary, etc. |
| SQL Validation | Rejects any SQL that isn't a single SELECT statement |
| PII Redaction | Strips email, phone, Aadhaar, PAN from responses |
| Confidence Tagging | Tags answers as Data / Data+Forecast / Simulation / AI Insight |

### Reasoning Trace

Every Genie response includes a `reasoning_trace` JSON object showing exactly how the answer was built. The frontend renders this as an expandable panel with:

- **Expert A tables**: Current inventory per SKU (stock, burn rate, coverage)
- **Expert B tables**: Projected demand per SKU for the target month
- **Math table**: Shortfall analysis with urgency badges (CRITICAL/HIGH/MEDIUM/LOW)
- **SQL view**: Raw SQL query and row count (for data queries)
- **What-If view**: Simulation parameters and at-risk SKU count

### CSV Export

The "Export CSV" button in the reasoning trace downloads a full reorder list with columns: SKU ID, Category, Sub-Category, Criticality, Current Stock, Avg Weekly Demand, Coverage, Projected Monthly Demand, Forecast Source, Shortfall, Recommended Order, Urgency.

### API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/api/genie/chat` | POST | Main chat — routes to agents, returns response + reasoning trace |
| `/api/genie/suggestions` | GET | Quick-action suggestions for the chat UI |
| `/api/genie/what-if` | POST | Structured what-if simulation (direct tool call) |
| `/api/genie/history` | GET | Conversation history for a session |
| `/api/genie/capabilities` | GET | Describes what Genie can do |
| `/api/genie/export-csv` | POST | Export stock advisory shortfall table as CSV |

### Genie File Structure

```
backend/app/genie/
├── __init__.py                 # Package init
├── engine.py                   # Main orchestrator — planner, routing, synthesis (427 lines)
├── llm_client.py               # Shared lazy Gemini 2.5 Flash client (52 lines)
├── guardrails.py               # Safety: injection, PII, SQL validation, confidence (297 lines)
├── schema_extractor.py         # Live SQLAlchemy → DDL text for LLM prompts (211 lines)
├── sql_agent.py                # NL → read-only SQL → execute → return rows (267 lines)
├── stock_advisor_agent.py      # Expert A+B+Math: inventory + forecast → shortfall (574 lines)
├── what_if_agent.py            # NL scenario detection → simulator routing (310 lines)
└── what_if.py                  # 4 simulation methods: lead_time, demand_spike, shelf_life, supplier_failure (335 lines)
```

---

## 13. Frontend Application

9 pages built with React 19, Vite 8, and Recharts:

| Route | Page | Description |
|---|---|---|
| `/` | Dashboard | 4 KPI cards, demand trend chart, category pie, 12-week forecast cards, stockout risk table |
| `/products` | Products | CRUD catalog with paginated table, search, category filter, modals |
| `/orders` | Orders | CRUD orders with status filters, line items display |
| `/suppliers` | Suppliers | CRUD suppliers with country/category filter |
| `/forecasting` | Forecasting | 3-tab view: SKU Explorer (chart + confidence bands), Reorder Panel, Forecast Calendar |
| `/genie` | Genie | AI chatbot with markdown rendering, reasoning trace panel, confidence badges, CSV export |
| `/users` | Users | CRUD user management with role filter |
| `/sap-sync` | SAP Sync | Connection status, test, 5 sync buttons, sync log |
| `/settings` | Settings | Theme toggle, notification prefs, profile editing |

### UI Components

| Component | Purpose |
|---|---|
| `Header` | Top bar with company name, location, live clock, LIVE indicator |
| `Sidebar` | Navigation with 9 items, brand logo, logout |
| `AppContext` | Theme (light/dark), notifications, sidebar state |

---

## 14. API Endpoints Reference

52 endpoints across 8 modules:

| # | Method | Endpoint | Module |
|---|---|---|---|
| 1 | GET | `/api/health` | Health |
| 2 | GET | `/api/dashboard/kpis` | Dashboard |
| 3 | GET | `/api/dashboard/charts/demand-trend` | Dashboard |
| 4 | GET | `/api/dashboard/charts/category-distribution` | Dashboard |
| 5 | GET | `/api/dashboard/charts/sales-by-region` | Dashboard |
| 6 | GET | `/api/dashboard/charts/category-forecast` | Dashboard |
| 7 | GET | `/api/dashboard/stockout-risk` | Dashboard |
| 8-13 | CRUD | `/api/products` | Products |
| 14-18 | CRUD | `/api/suppliers` | Suppliers |
| 19-23 | CRUD | `/api/orders` | Orders |
| 24-28 | CRUD | `/api/users` | Users |
| 29 | GET | `/api/sap/sync-status` | SAP |
| 30 | POST | `/api/sap/config` | SAP |
| 31 | POST | `/api/sap/test-connection` | SAP |
| 32 | POST | `/api/sap/sync` | SAP |
| 33 | POST | `/api/forecast/train` | Forecast |
| 34 | GET | `/api/forecast/predict` | Forecast |
| 35 | GET | `/api/forecast/compare` | Forecast |
| 36 | GET | `/api/forecast/metrics` | Forecast |
| 37 | GET | `/api/forecast/ensemble-weights` | Forecast |
| 38 | POST | `/api/forecast/retrain` | Forecast |
| 39 | GET | `/api/forecast/models` | Forecast |
| 40 | GET | `/api/forecast/summary` | Forecast |
| 41 | GET | `/api/forecast/products` | Forecast |
| 42 | GET | `/api/forecast/sku-explorer` | Forecast |
| 43 | GET | `/api/forecast/reorder-recommendations` | Forecast |
| 44 | GET | `/api/forecast/drift-monitor` | Forecast |
| 45 | GET | `/api/forecast/export-csv` | Forecast |
| 46 | GET | `/api/forecast/calendar` | Forecast |
| 47 | POST | `/api/genie/chat` | Genie |
| 48 | GET | `/api/genie/suggestions` | Genie |
| 49 | POST | `/api/genie/what-if` | Genie |
| 50 | GET | `/api/genie/history` | Genie |
| 51 | GET | `/api/genie/capabilities` | Genie |
| 52 | POST | `/api/genie/export-csv` | Genie |

---

## 15. Project File Structure

```
V2_vst/
├── PROJECT_INFO.md              # This file
├── README.md                    # Setup instructions
├── PROJECT_CONTEXT.md           # Living project context/decision log
├── docker-compose.yml           # 3-service Docker setup
├── start_app.bat                # Local startup script
├── .gitignore
├── model_comparison.png         # Saved chart image
├── timeseries_models.png        # Saved chart image
├── VST(logo).png                # Company logo
├── debug_training.ipynb         # Training notebook
│
├── data/                        # CSV seed data (7 files, ~2.2 MB)
│   ├── fact_sales.csv           # 1.68 MB — 4 years of weekly sales
│   ├── demand_forecast.csv      # 527 KB — pre-generated forecasts
│   ├── dim_products.csv         # 15 KB — 200 SKUs
│   ├── dim_suppliers.csv        # 1.7 KB — 28 suppliers
│   ├── dim_users.csv            # 411 B — 5 users
│   ├── fact_external.csv        # 6.8 KB — monsoon/crop/macro data
│   └── fact_orders.csv          # 436 B — order data
│
├── backend/
│   ├── .env                     # Config (DB, Gemini API key, SAP)
│   ├── requirements.txt         # 23 Python dependencies
│   ├── Dockerfile
│   ├── vst_ims.db               # SQLite database (11 MB)
│   ├── trained_models/          # 8 persisted model files
│   │   ├── xgboost_global.joblib
│   │   ├── lightgbm_global.joblib
│   │   ├── arima_EN-DIE-0002.joblib
│   │   ├── sarima_EN-DIE-0002.joblib
│   │   ├── prophet_EN-DIE-0002.joblib
│   │   ├── holt_winters_EN-DIE-0002.joblib
│   │   ├── ensemble_weights.json
│   │   └── training_history.json
│   └── app/
│       ├── main.py              # FastAPI app, router registration
│       ├── config.py            # Pydantic Settings
│       ├── database.py          # SQLAlchemy engine, session
│       ├── models/__init__.py   # 12 ORM models
│       ├── schemas/__init__.py  # 18 Pydantic schemas
│       ├── routers/
│       │   ├── dashboard.py     # 6 endpoints
│       │   ├── products.py      # 6 endpoints
│       │   ├── suppliers.py     # 5 endpoints
│       │   ├── orders.py        # 5 endpoints
│       │   ├── users.py         # 5 endpoints
│       │   ├── sap_sync.py      # 4 endpoints
│       │   ├── forecast.py      # 14 endpoints
│       │   └── genie.py         # 6 endpoints
│       ├── forecasting/
│       │   ├── models.py        # 6 model implementations
│       │   ├── ensemble.py      # AdaptiveEnsemble
│       │   ├── data_pipeline.py # Feature engineering
│       │   ├── metrics.py       # Error metrics
│       │   └── rl_feedback.py   # Bandit optimizer
│       ├── genie/
│       │   ├── engine.py        # Orchestrator
│       │   ├── llm_client.py    # Gemini client
│       │   ├── guardrails.py    # Safety system
│       │   ├── schema_extractor.py
│       │   ├── sql_agent.py     # NL → SQL
│       │   ├── stock_advisor_agent.py
│       │   ├── what_if_agent.py
│       │   └── what_if.py       # Simulator
│       └── services/
│           └── sap_connector.py # SAP RFC/OData
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    ├── index.html
    ├── Dockerfile
    └── src/
        ├── main.jsx
        ├── App.jsx              # Router with 9 routes
        ├── App.css              # Global styles (1400+ lines)
        ├── context/AppContext.jsx
        ├── components/
        │   ├── Header.jsx
        │   └── Sidebar.jsx
        ├── services/api.js      # 30+ API functions
        └── pages/
            ├── Dashboard.jsx    # 503 lines
            ├── Products.jsx     # 280 lines
            ├── Orders.jsx       # 257 lines
            ├── Suppliers.jsx    # 157 lines
            ├── Users.jsx        # 147 lines
            ├── Forecasting.jsx  # 624 lines
            ├── Genie.jsx        # 479 lines
            ├── SapSync.jsx      # 131 lines
            └── Settings.jsx     # 60 lines
```

---

## 16. Getting Started

### Local Development

```bash
# Backend
cd backend
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev
```

### Docker

```bash
docker-compose up --build
```

### Environment Variables

```env
# Database
DATABASE_URL=sqlite:///path/to/vst_ims.db

# Gemini (for Genie chatbot)
GEMINI_API_KEY=your_key_here

# SAP (optional)
SAP_HOST=
SAP_USER=
SAP_PASSWORD=
```

---

## ⚠️ Build vs Production — Safety Rules

> **All agents (AI and human) MUST follow these rules. No exceptions.**

| Rule | Detail |
|------|--------|
| **Never touch production without explicit approval** | Any script, migration, or seed that targets the cloud database (Supabase/Render) requires the user's explicit go-ahead first. |
| **Always clarify environment** | Before executing any command, confirm: is this Build (local SQLite) or Production (cloud PostgreSQL)? |
| **Default to Build/local** | All scripts, seeder runs, and DB operations default to local SQLite (`vst_ims.db`). Production only with `--cloud` flag AND user confirmation. |
| **Flag production-risk changes** | If a code change or script could affect production data, flag it clearly before proceeding. |
| **No blind `DELETE FROM`** | Never wipe production tables without a backup. |

**Environment identifiers:**
- **Build** = `sqlite:///vst_ims.db` (local, safe to reset)
- **Production** = `postgresql://...supabase.com` (cloud, live data)

---

*Last updated: August 2026*
