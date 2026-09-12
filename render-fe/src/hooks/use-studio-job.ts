import { useCallback, useEffect, useRef, useState } from 'react';

import type {
  DesignFormValues,
  DesignPreview,
  PreparedModel,
  StudioGateway,
  StudioJob,
  StudioVideoJob,
} from '../types/studio';

const ACTIVE_VIEW_SET_KEY = 'v365.activeViewSetId';

export function useStudioJob(gateway: StudioGateway) {
  const [job, setJob] = useState<StudioJob | null>(null);
  const [videoJob, setVideoJob] = useState<StudioVideoJob | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isPreparingModel, setIsPreparingModel] = useState(false);
  const [isPreviewingDesign, setIsPreviewingDesign] = useState(false);
  const [preparedModel, setPreparedModel] = useState<PreparedModel | null>(null);
  const [designPreview, setDesignPreview] = useState<DesignPreview | null>(null);
  const [isSubmittingVideo, setIsSubmittingVideo] = useState(false);
  const [isSubmittingReview, setIsSubmittingReview] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorTitle, setErrorTitle] = useState('Không thể tạo phương án diễn họa');
  const activeViewSet = useRef<string | null>(null);
  const activeVideoJob = useRef<string | null>(null);
  const terminalOutputRetries = useRef(0);

  const prepareModel = useCallback(async (file: File) => {
    setIsPreparingModel(true);
    setError(null);
    setErrorTitle('Không thể phân tích mô hình');
    setDesignPreview(null);
    try {
      const prepared = await gateway.prepareModel(file);
      setPreparedModel(prepared);
    } catch (reason) {
      setPreparedModel(null);
      setError(reason instanceof Error ? reason.message : 'Không thể phân tích mô hình');
    } finally {
      setIsPreparingModel(false);
    }
  }, [gateway]);

  const previewDesign = useCallback(async (values: DesignFormValues) => {
    if (!preparedModel) {
      setErrorTitle('Chưa phân tích mô hình');
      setError('Hãy phân tích file RVT trước khi kiểm tra phương án.');
      return;
    }
    setIsPreviewingDesign(true);
    setError(null);
    setErrorTitle('Không thể kiểm tra phương án');
    try {
      setDesignPreview(await gateway.previewDesign(values, preparedModel));
    } catch (reason) {
      setDesignPreview(null);
      setError(reason instanceof Error ? reason.message : 'Không thể kiểm tra phương án');
    } finally {
      setIsPreviewingDesign(false);
    }
  }, [gateway, preparedModel]);

  const invalidateDesignPreview = useCallback(() => setDesignPreview(null), []);

  const resetPreparedModel = useCallback(() => {
    setPreparedModel(null);
    setDesignPreview(null);
  }, []);

  const submit = useCallback(
    async (values: DesignFormValues) => {
      if (!preparedModel || !designPreview) {
        setErrorTitle('Chưa xác nhận phương án');
        setError('Hãy phân tích model và kiểm tra phương án trước khi tạo Design Master.');
        return;
      }
      setIsSubmitting(true);
      setError(null);
      setErrorTitle('Không thể tạo phương án diễn họa');
      setVideoJob(null);
      activeVideoJob.current = null;
      terminalOutputRetries.current = 0;
      try {
        const created = await gateway.createDesign(
          values,
          preparedModel,
          designPreview.previewToken,
        );
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
    [designPreview, gateway, preparedModel],
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
    async (action: 'approve' | 'reject' | 'reject_all' | 'retry') => {
      if (!activeViewSet.current) return;
      setIsSubmittingReview(true);
      setError(null);
      setErrorTitle(
        action === 'approve'
          ? 'Không thể duyệt bộ ảnh'
          : action === 'reject' || action === 'reject_all'
            ? 'Không thể tạo lại Design Master'
            : 'Không thể chạy lại pipeline',
      );
      try {
        const updated =
          action === 'approve'
            ? await gateway.approveViewSet(activeViewSet.current)
            : action === 'reject'
              ? await gateway.rejectDesignMaster(activeViewSet.current)
              : action === 'reject_all'
                ? await gateway.rejectViewSet(activeViewSet.current)
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
  const rejectMaster = useCallback(() => transitionReview('reject'), [transitionReview]);
  const rejectViewSet = useCallback(() => transitionReview('reject_all'), [transitionReview]);
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
    if (!job || ['failed', 'human_review', 'design_master_review'].includes(job.state)) return undefined;
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
    isPreparingModel,
    isPreviewingDesign,
    preparedModel,
    designPreview,
    isSubmittingVideo,
    isSubmittingReview,
    error,
    errorTitle,
    submit,
    prepareModel,
    previewDesign,
    invalidateDesignPreview,
    resetPreparedModel,
    refresh,
    approve,
    rejectMaster,
    rejectViewSet,
    retry,
    generateVideo,
  };
}
