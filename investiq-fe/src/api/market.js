import { request } from './client.js';

export const marketApi = {
  news: () => request('/market/news'),
  status: () => request('/market/status'),
  sectors: () => request('/sectors'),
  instruments: (params = {}) => request('/instruments?' + new URLSearchParams(params)),
  quotes: (identifiers, asOf) => request('/quotes?' + new URLSearchParams({
    instrument_ids: identifiers.join(','), ...(asOf ? { as_of: asOf } : {}),
  })),
};
