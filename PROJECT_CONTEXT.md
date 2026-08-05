# VST Tillers & Tractors — Project Context & Decision Log

> **Purpose**: Living document to preserve context across sessions. Feed this file to the model at the start of each new conversation to restore full project state.

---

## 🏭 Project Overview

- **Client**: VST Tillers and Tractors Ltd. (MNC, Malur facility)
- **Domain**: Agricultural machinery — tillers, tractors, pumps, diesel engines
- **Goal**: RL-driven Demand Forecasting & Inventory Management MVP
- **Stack**: Python, pandas, scikit-learn, matplotlib/seaborn, Gymnasium (RL)
- **Future**: React/FastAPI dashboard, LLM chatbot interface

---

## 📦 Product Categories (5)

| Category | Examples | Seasonality Pattern |
|---|---|---|
| Spare Parts | Filters, piston kits, gaskets | Post-harvest maintenance spike (Nov–Dec) |
| Lubricants/Consumables | Engine oils, greases | Steady demand, mild seasonal uptick |
| Electric Pumps | Submersible, centrifugal, domestic | **Heavy monsoon spike (May–Jun pre-monsoon buying)** |
| Engines | Diesel engines, power tiller engines | Moderate, tracks sowing seasons |
| Precision Components | Locomotive parts, rotary assemblies | Steady, high-value low-volume |

---

## 🌍 Supply Chain Geography

| Origin | Products | Lead Time | Volatility |
|---|---|---|---|
| Japan | Precision components, engines | 45–90 days | Medium |
| China | Pumps, bulk spare parts | 30–75 days | **Highest** |
| Germany | Precision components | 60–120 days | Medium |
| India (domestic) | Spare parts, lubricants | 7–30 days | Lowest |

---

## 🗓️ Agricultural Seasonality (India)

- **Kharif Season**: Jun–Oct (monsoon crops: rice, cotton, soybean)
- **Rabi Season**: Nov–Mar (winter crops: wheat, mustard, gram)
- **Monsoon**: Jun–Sep (SW monsoon), critical driver for pump demand
- **Post-Harvest Maintenance**: Nov–Dec (tiller/tractor servicing window)

---

## 📐 Architecture (Planned)

```
Two-Tower Architecture:
├── Tower 1: Demand Forecasting (XGBoost/LightGBM/LSTM)
│   └── Inputs: historical sales + external factors → predicted demand
└── Tower 2: RL Agent (Gymnasium)
    ├── State: inventory, pipeline, forecast, seasonality, lead times
    ├── Action: order quantities per SKU
    └── Reward: fill rate (+) vs holding cost (-) vs stockout cost (-)
```

---

## 📝 Change Log

| Date | Phase | Change | Details |
|---|---|---|---|
| 2026-08-03 | Phase 1 | Project initialized | Synthetic data gen + EDA. 200 SKUs, weekly granularity, 4-year history (2022-2025). |
| 2026-08-03 | Phase 1 | Dashboard generated | Light-theme HTML dashboard with real INR KPIs. 4 KPI cards, 4 charts, interactive table, filter/search, export CSV. Served at http://localhost:8765/vst_inventory_dashboard.html |
| 2026-08-03 | Phase 2 | ML/RL Engine Complete | Tower 1 (XGBoost) MAPE = 19.1%. Tower 2 (PPO RL) Fill Rate = 97.9% vs 87.2% baseline (+10.7 pp). Saved models to `models/` and charts 08-13 to `output/charts/`. |


---

## 🔮 Future Scope (Do Not Build Yet)

1. **Phase 2**: ML forecasting (Tower 1) + RL agent (Tower 2)
2. **Phase 3**: React/FastAPI full-stack dashboard
3. **Phase 4**: LLM chatbot interface for natural-language supply chain queries
4. **Phase 5**: Scale to 5,000+ SKUs, real data integration

---

## 💡 Key Design Decisions

| Decision | Choice | Rationale |
|---|---|---|
| SKU count (MVP) | 200 | Fast iteration; parameterized config to scale to 5000+ |
| Time granularity | Weekly | Standard for supply chain planning; reduces data volume 7× |
| Date range | 2022-01-01 to 2025-12-31 | 4 years gives enough history for seasonality patterns |
| Code structure | Python modules + script | Cleaner than .ipynb for version control; convertible to notebook |
| Random seed | 42 | Reproducibility |
