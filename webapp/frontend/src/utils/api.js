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
export const getAgentDecisions   = (symbols)       => api.get(`/agent/decisions${symbols ? `?symbols=${symbols}` : ''}`)
export const getBacktestSummary  = (symbols)       => api.get(`/backtest/summary${symbols ? `?symbols=${symbols}` : ''}`)

export default api
