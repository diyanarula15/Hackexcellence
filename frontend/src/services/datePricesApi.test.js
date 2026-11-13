import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from './apiClient.js';
import { DATE_PRICES_PATH, getDatePrices } from './datePricesApi.js';

const TRIP = {
  origin: 'DEL',
  destination: 'GOA',
  adults: 2,
  budget_inr: 300000,
};
const RANGE = { rangeStart: '2027-04-01', rangeEnd: '2027-04-30' };

const jsonResponse = (status, body, statusText = '') => ({
  ok: status >= 200 && status < 300,
  status,
  statusText,
  json: async () => body,
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('getDatePrices', () => {
  it('POSTs the trip fields plus range_start and range_end to /api/date-prices', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { dates: [] }));
    vi.stubGlobal('fetch', fetchMock);

    await getDatePrices(TRIP, RANGE);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(new URL(String(url)).pathname).toBe('/api/date-prices');
    expect(DATE_PRICES_PATH).toBe('/api/date-prices');
    expect(init.method).toBe('POST');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ ...TRIP, range_start: '2027-04-01', range_end: '2027-04-30' });
  });

  it('passes the AbortSignal through to fetch', async () => {
    const fetchMock = vi.fn(async () => jsonResponse(200, { dates: [] }));
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();

    await getDatePrices(TRIP, RANGE, { signal: controller.signal });

    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it('returns the parsed JSON body', async () => {
    const payload = { dates: [{ date: '2027-04-10', status: 'FOUND' }], range_fully_evaluated: true };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(200, payload)));

    await expect(getDatePrices(TRIP, RANGE)).resolves.toEqual(payload);
  });

  it('throws an ApiError with status 422 and keeps the response body on a 422', async () => {
    const payload = { message: 'range_end is before range_start' };
    vi.stubGlobal('fetch', vi.fn(async () => jsonResponse(422, payload, 'Unprocessable Entity')));

    const error = await getDatePrices(TRIP, RANGE).catch((e) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.body).toEqual(payload);
    expect(error.message).toBe('range_end is before range_start');
  });

  it('rejects with ApiError status 0 on a network failure and never resolves with data (no mock fallback)', async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError('Failed to fetch');
    });
    vi.stubGlobal('fetch', fetchMock);

    const outcome = await getDatePrices(TRIP, RANGE).then(
      (value) => ({ resolved: value }),
      (error) => ({ rejected: error }),
    );

    expect(outcome).toHaveProperty('rejected');
    expect(outcome.rejected).toBeInstanceOf(ApiError);
    expect(outcome.rejected.status).toBe(0);
    expect(outcome.resolved).toBeUndefined();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
