import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  DesignFormValues,
  StudioGateway,
  StudioJob,
  StudioVideoJob,
} from '../types/studio';

export function useStudioJob(gateway: StudioGateway) {
  const [job, setJob] = useState<StudioJob | null>(null);
  const [videoJob, setVideoJob] = useState<StudioVideoJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmittingVideo, setIsSubmittingVideo] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorTitle, setErrorTitle] = useState('Không thể tạo phương án diễn họa');
  const activeViewSet = useRef<string | null>(null);
  const activeVideoJob = useRef<string | null>(null);
  const terminalOutputRetries = useRef(0);

  const submit = useCallback(
    async (values: DesignFormValues) => {
      setIsSubmitting(true);
      setError(null);
      setErrorTitle('Không thể tạo phương án diễn họa');
      setVideoJob(null);
      activeVideoJob.current = null;
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
    setErrorTitle('Không thể tạo phương án diễn họa');
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

  const generateVideo = useCallback(async () => {
    if (!activeViewSet.current) return;
    setIsSubmittingVideo(true);
    setError(null);
    setErrorTitle('Không thể tạo video trình diễn');
    try {
      const created = await gateway.createVideo(activeViewSet.current);
      activeVideoJob.current = created.videoJobId;
      setVideoJob(created);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thể tạo video trình diễn');
    } finally {
      setIsSubmittingVideo(false);
    }
  }, [gateway]);

  const refreshVideo = useCallback(async () => {
    if (!activeVideoJob.current) return;
    setErrorTitle('Không thể tạo video trình diễn');
    try {
      const updated = await gateway.getVideoJob(activeVideoJob.current);
      setVideoJob(updated);
      if (updated.state === 'completed') {
        await refresh();
      }
      setError(
        updated.state === 'failed'
          ? updated.errorMessage || 'Pipeline video đã dừng do lỗi không xác định'
          : null,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Không thể cập nhật video');
    }
  }, [gateway, refresh]);

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

  useEffect(() => {
    if (!videoJob || ['completed', 'failed'].includes(videoJob.state)) return undefined;
    const timer = window.setInterval(() => void refreshVideo(), 3000);
    return () => window.clearInterval(timer);
  }, [refreshVideo, videoJob]);

  return {
    job,
    videoJob,
    isSubmitting,
    isSubmittingVideo,
    error,
    errorTitle,
    submit,
    refresh,
    generateVideo,
  };
}
