import { useCallback, useEffect, useRef, useState } from 'react';

import type { DesignFormValues, StudioGateway, StudioJob } from '../types/studio';

export function useStudioJob(gateway: StudioGateway) {
  const [job, setJob] = useState<StudioJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeViewSet = useRef<string | null>(null);
  const terminalOutputRetries = useRef(0);

  const submit = useCallback(
    async (values: DesignFormValues) => {
      setIsSubmitting(true);
      setError(null);
      terminalOutputRetries.current = 0;
      try {
        const created = await gateway.createDesign(values);
        activeViewSet.current = created.viewSetId;
        setJob(created);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Không thể tạo phiên diễn họa');
      } finally {
        setIsSubmitting(false);
      }
    },
    [gateway],
  );

  const refresh = useCallback(async () => {
    if (!activeViewSet.current) return;
    try {
      const updated = await gateway.getJob(activeViewSet.current);
      setJob(updated);
      setError(
        updated.state === 'failed'
          ? updated.errorMessage || 'Pipeline diễn họa đã dừng do lỗi không xác định'
          : null,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thể cập nhật tiến trình');
    }
  }, [gateway]);

  useEffect(() => {
    if (!job || job.state === 'failed') return undefined;
    if (job.state === 'completed') {
      if (job.outputs.length || terminalOutputRetries.current >= 5) return undefined;
      terminalOutputRetries.current += 1;
      const timeout = window.setTimeout(() => void refresh(), 1_000);
      return () => window.clearTimeout(timeout);
    }
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [job, refresh]);

  return { job, isSubmitting, error, submit, refresh };
}
