import { useState, useEffect, useCallback, useRef } from 'react';
import { ciApi, CICompetitor, CIItem, CISearchParams } from '../services/api';

// ── useRadarCompetitors ────────────────────────────────────────────────────

export function useRadarCompetitors() {
  const [competitors, setCompetitors] = useState<CICompetitor[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ciApi.competitors();
      setCompetitors(res.data);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setCompetitors([]);
      } else {
        setError(err.response?.data?.detail || 'Failed to load competitors');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetch(); }, [fetch]);

  return { competitors, loading, error, refetch: fetch };
}

// ── useRadarSearch ─────────────────────────────────────────────────────────

export function useRadarSearch() {
  const [results, setResults] = useState<CIItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [total, setTotal] = useState(0);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const paramsRef = useRef<CISearchParams>({});

  const search = useCallback(async (params: CISearchParams, append = false) => {
    paramsRef.current = params;
    try {
      setLoading(true);
      setError(null);
      const limit = params.limit || 20;
      const res = await ciApi.search({ ...params, limit });
      const items = res.data;

      if (append) {
        setResults(prev => [...prev, ...items]);
      } else {
        setResults(items);
      }
      setTotal(items.length);
      setHasMore(items.length >= limit);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setResults(append ? results : []);
        setHasMore(false);
      } else {
        setError(err.response?.data?.detail || 'Search failed');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const debouncedSearch = useCallback((params: CISearchParams) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => search(params), 300);
  }, [search]);

  const loadMore = useCallback(() => {
    const params = paramsRef.current;
    const offset = (params.offset || 0) + (params.limit || 20);
    search({ ...params, offset }, true);
  }, [search]);

  const reset = useCallback(() => {
    setResults([]);
    setError(null);
    setHasMore(false);
    setTotal(0);
  }, []);

  return { results, loading, error, hasMore, total, search, debouncedSearch, loadMore, reset };
}

// ── useRadarSimilar ────────────────────────────────────────────────────────

export function useRadarSimilar() {
  const [similar, setSimilar] = useState<CIItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetch = useCallback(async (itemId: string, limit = 10) => {
    try {
      setLoading(true);
      setError(null);
      const res = await ciApi.similar(itemId, limit);
      const data = res.data;
      setSimilar(Array.isArray(data) ? data : (data as any).results || []);
    } catch (err: any) {
      if (err.response?.status === 404) {
        setSimilar([]);
      } else {
        setError(err.response?.data?.detail || 'Failed to load similar items');
      }
    } finally {
      setLoading(false);
    }
  }, []);

  const reset = useCallback(() => {
    setSimilar([]);
    setError(null);
  }, []);

  return { similar, loading, error, fetch, reset };
}
