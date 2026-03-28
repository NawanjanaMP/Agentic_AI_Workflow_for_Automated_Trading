// src/utils/api.js
// Central API client — all calls go through here

import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || '/api'

const api = axios.create({
  baseURL: BASE_URL,
  timeout: 30000,
})

export const getSymbols          = ()              => api.get('/symbols')
export const getPriceData        = (sym, days)     => api.get(`/price/${sym}?days=${days}`)
export const getLatestSignals    = ()              => api.get('/signals/latest')
export const getPortfolioMetrics = ()              => api.get('/metrics/portfolio')
export const getLatestNews       = ()              => api.get('/news/latest')
export const getHealth           = ()              => api.get('/health')
// Phase 4 endpoints are heavy (S3 loads + ML) — use 3-minute timeout
export const getAgentDecisions   = (symbols)       => api.get(`/agent/decisions${symbols ? `?symbols=${symbols}` : ''}`,  { timeout: 180000 })
export const getBacktestSummary  = (symbols)       => api.get(`/backtest/summary${symbols ? `?symbols=${symbols}` : ''}`, { timeout: 180000 })

// Phase 5 endpoints — Backtrader + walk-forward + Monte Carlo (10-min timeout)
export const getBacktestPhase5       = (symbols, useCache = true) =>
  api.get(`/backtest/phase5?symbols=${symbols || 'AAPL,MSFT,NVDA,TSLA,SPY,QQQ'}&use_cache=${useCache}`, { timeout: 600000 })
export const getBacktestPhase5Symbol = (symbol, useCache = true) =>
  api.get(`/backtest/phase5/${symbol}?use_cache=${useCache}`, { timeout: 300000 })
export const getWalkForward          = (symbols, nSplits = 5) =>
  api.get(`/backtest/walkforward?symbols=${symbols || 'AAPL,MSFT,NVDA,TSLA,SPY,QQQ'}&n_splits=${nSplits}`, { timeout: 300000 })

export default api
