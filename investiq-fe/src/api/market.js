import { request } from './client.js';

export const marketApi = {
  sectors: () => request('/sectors'),
  instruments: (params = {}) => request('/instruments?' + new URLSearchParams(params)),
  quotes: (identifiers, asOf) => request('/quotes?' + new URLSearchParams({
    instrument_ids: identifiers.join(','), ...(asOf ? { as_of: asOf } : {}),
  })),
};
