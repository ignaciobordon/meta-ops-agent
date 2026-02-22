import { useState, useEffect, useRef, useCallback } from 'react';
import { opsApi, JobRunItem } from '../services/api';

interface UseJobPollingResult {
  status: string | null;
  error: string | null;
  data: JobRunItem | null;
  isPolling: boolean;
}

const TERMINAL_STATES = ['succeeded', 'failed', 'dead', 'canceled'];

export function useJobPolling(
  jobId: string | null,
  intervalMs: number = 2000,
  maxPollDurationMs: number = 120000,
): UseJobPollingResult {
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [data, setData] = useState<JobRunItem | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
    setIsPolling(false);
    startTimeRef.current = null;
  }, []);

  useEffect(() => {
    if (!jobId) {
      stopPolling();
      setStatus(null);
      setError(null);
      setData(null);
      return;
    }

    setIsPolling(true);
    setError(null);
    setStatus('queued');
    startTimeRef.current = Date.now();

    const poll = async () => {
      // Check polling timeout
      if (startTimeRef.current && (Date.now() - startTimeRef.current) > maxPollDurationMs) {
        setError('Job timed out. The operation is taking longer than expected. You can retry or check the Ops Console.');
        setStatus('timeout');
        stopPolling();
        return;
      }

      try {
        const res = await opsApi.getJob(jobId);
        const job = res.data;
        setData(job);
        setStatus(job.status);

        if (TERMINAL_STATES.includes(job.status)) {
          stopPolling();
          if (job.status === 'failed' || job.status === 'dead') {
            setError(job.last_error_message || 'Job failed');
          }
        }
      } catch (err: any) {
        setError(err.response?.data?.detail || 'Failed to poll job status');
        stopPolling();
      }
    };

    poll();
    intervalRef.current = setInterval(poll, intervalMs);

    return () => stopPolling();
  }, [jobId, intervalMs, maxPollDurationMs, stopPolling]);

  return { status, error, data, isPolling };
}
