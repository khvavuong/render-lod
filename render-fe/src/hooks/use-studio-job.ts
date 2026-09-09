import { useCallback, useEffect, useRef, useState } from 'react';

import type { DesignFormValues, StudioGateway, StudioJob, WorkflowState } from '../types/studio';

const TERMINAL_STATES = new Set<WorkflowState>(['completed', 'failed']);

export function useStudioJob(gateway: StudioGateway) {
  const [job, setJob] = useState<StudioJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const activeViewSet = useRef<string | null>(null);

  const submit = useCallback(
    async (values: DesignFormValues) => {
      setIsSubmitting(true);
      setError(null);
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
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thể cập nhật tiến trình');
    }
  }, [gateway]);

  useEffect(() => {
    if (!job || TERMINAL_STATES.has(job.state)) return undefined;
    const timer = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(timer);
  }, [job, refresh]);

  return { job, isSubmitting, error, submit, refresh };
}
