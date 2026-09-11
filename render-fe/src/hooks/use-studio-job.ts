import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  DesignFormValues,
  StudioGateway,
  StudioJob,
  StudioVideoJob,
} from '../types/studio';

const ACTIVE_VIEW_SET_KEY = 'v365.activeViewSetId';

export function useStudioJob(gateway: StudioGateway) {
  const [job, setJob] = useState<StudioJob | null>(null);
  const [videoJob, setVideoJob] = useState<StudioVideoJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isSubmittingVideo, setIsSubmittingVideo] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
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
        window.localStorage.setItem(ACTIVE_VIEW_SET_KEY, created.viewSetId);
        setJob(created);
        setError(
          created.state === 'failed'
            ? created.errorMessage || 'Pipeline diễn họa đã dừng do lỗi không xác định'
            : null,
        );
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

  const transitionReview = useCallback(
    async (action: 'approve' | 'retry') => {
      if (!activeViewSet.current) return;
      setIsSubmittingReview(true);
      setError(null);
      setErrorTitle(
        action === 'approve'
          ? 'Không thể duyệt bộ ảnh'
          : 'Không thể chạy lại pipeline',
      );
      try {
        const updated =
          action === 'approve'
            ? await gateway.approveViewSet(activeViewSet.current)
            : await gateway.retryViewSet(activeViewSet.current);
        setJob(updated);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : 'Không thể cập nhật phiên diễn họa');
      } finally {
        setIsSubmittingReview(false);
      }
    },
    [gateway],
  );

  const approve = useCallback(() => transitionReview('approve'), [transitionReview]);
  const retry = useCallback(() => transitionReview('retry'), [transitionReview]);

  useEffect(() => {
    const persisted = window.localStorage.getItem(ACTIVE_VIEW_SET_KEY);
    if (!persisted || activeViewSet.current) return;
    activeViewSet.current = persisted;
    void gateway
      .getJob(persisted)
      .then((restored) => {
        setJob(restored);
        setError(
          restored.state === 'failed'
            ? restored.errorMessage || 'Pipeline diễn họa đã dừng do lỗi không xác định'
            : null,
        );
      })
      .catch(() => {
        window.localStorage.removeItem(ACTIVE_VIEW_SET_KEY);
        activeViewSet.current = null;
      });
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
    if (!job || ['failed', 'human_review'].includes(job.state)) return undefined;
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
    isSubmittingReview,
    error,
    errorTitle,
    submit,
    refresh,
    approve,
    retry,
    generateVideo,
  };
}
