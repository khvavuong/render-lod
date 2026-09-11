import { buildUserRenderIntent } from '../domain/design-brief';
import type {
  DesignFormValues,
  DesignOptions,
  CertificationState,
  IntentWarning,
  OutputArtifact,
  StudioGateway,
  StudioJob,
  StudioVideoJob,
  VideoJobState,
  WorkflowState,
} from '../types/studio';

interface DesignRevisionResponse {
  design_revision: string;
  warnings?: IntentWarning[];
}

interface LatestModelResponse {
  model_revision: string;
  ready: boolean;
}

interface ViewSetResponse {
  job_id: string;
  trace_id: string;
  view_set_id: string;
  design_revision: string;
  state: WorkflowState;
  certification_state?: CertificationState;
  error_message?: string | null;
}

interface OutputsResponse {
  outputs: OutputArtifact[];
}

interface VideoJobResponse {
  video_job_id: string;
  view_set_id: string;
  state: VideoJobState;
  estimated_cost_usd: number;
  output_url?: string | null;
  error_message?: string | null;
}

interface ApiValidationIssue {
  loc?: Array<string | number>;
  msg?: string;
}

function formatApiError(body: unknown, status: number): string {
  if (!body || typeof body !== 'object' || !('detail' in body)) {
    return `Yêu cầu thất bại (${status})`;
  }

  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail === 'string') {
    return detail;
  }
  if (Array.isArray(detail)) {
    const issues = detail
      .map((item: ApiValidationIssue) => {
        const location = item.loc?.filter((part) => part !== 'body').join('.');
        if (!item.msg) return null;
        return location ? `${location}: ${item.msg}` : item.msg;
      })
      .filter((item): item is string => Boolean(item));
    if (issues.length) {
      return `Dữ liệu chưa hợp lệ: ${issues.join('; ')}`;
    }
  }
  if (detail && typeof detail === 'object') {
    try {
      return JSON.stringify(detail);
    } catch {
      // Fall through to the status-based message below.
    }
  }
  return `Yêu cầu thất bại (${status})`;
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { 'Content-Type': 'application/json', ...init?.headers },
    });
  } catch {
    throw new Error('Không thể kết nối tới máy chủ. Hãy kiểm tra FastAPI đang chạy bằng lệnh “make api”.');
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as unknown;
    throw new Error(formatApiError(body, response.status));
  }
  return (await response.json()) as T;
}

function toJob(
  job: ViewSetResponse,
  outputs: OutputArtifact[] = [],
  intentWarnings: IntentWarning[] = [],
): StudioJob {
  return {
    jobId: job.job_id,
    traceId: job.trace_id,
    viewSetId: job.view_set_id,
    designRevision: job.design_revision,
    state: job.state,
    certificationState: job.certification_state ?? 'base_pbr',
    outputs,
    intentWarnings,
    errorMessage: job.error_message ?? undefined,
  };
}

function toVideoJob(job: VideoJobResponse): StudioVideoJob {
  return {
    videoJobId: job.video_job_id,
    viewSetId: job.view_set_id,
    state: job.state,
    estimatedCostUsd: job.estimated_cost_usd,
    outputUrl: job.output_url ?? undefined,
    errorMessage: job.error_message ?? undefined,
  };
}

export class HttpStudioGateway implements StudioGateway {
  async getDesignOptions(): Promise<DesignOptions> {
    return request<DesignOptions>('/v1/design-options');
  }

  async createDesign(values: DesignFormValues): Promise<StudioJob> {
    if (!values.modelFile) {
      throw new Error('Chưa chọn file RVT');
    }
    const model = await request<LatestModelResponse>('/v1/models', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-Filename': encodeURIComponent(values.modelFile.name),
      },
      body: values.modelFile,
    });
    if (!model.ready) {
      throw new Error(
        `Model ${model.model_revision} đã tải lên nhưng máy chủ chưa cấu hình đầy đủ APS để trích xuất hình học.`,
      );
    }
    const revision = await request<DesignRevisionResponse>(
      `/v1/projects/${encodeURIComponent(values.projectId)}/design-revisions`,
      {
        method: 'POST',
        body: JSON.stringify({
          model_revision: model.model_revision,
          intent: buildUserRenderIntent(values),
        }),
      },
    );
    const job = await request<ViewSetResponse>(
      `/v1/design-revisions/${encodeURIComponent(revision.design_revision)}/view-sets`,
      {
        method: 'POST',
        body: JSON.stringify({
          model_revision: model.model_revision,
          profile: 'marketing_hero',
          render_profile: 'standard_eevee',
        }),
      },
    );
    const outputResponse = await request<OutputsResponse>(
      `/v1/view-sets/${encodeURIComponent(job.view_set_id)}/outputs`,
    ).catch(() => ({ outputs: [] }));
    return toJob(job, outputResponse.outputs, revision.warnings);
  }

  async getJob(viewSetId: string): Promise<StudioJob> {
    const job = await request<ViewSetResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}`,
    );
    const outputRequest = request<OutputsResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}/outputs`,
    );
    const outputResponse =
      job.state === 'completed'
        ? await outputRequest
        : await outputRequest.catch(() => ({ outputs: [] }));
    return toJob(job, outputResponse.outputs);
  }

  private async transitionViewSet(viewSetId: string, action: 'approve' | 'retry') {
    const job = await request<ViewSetResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}/${action}`,
      { method: 'POST' },
    );
    const outputResponse = await request<OutputsResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}/outputs`,
    ).catch(() => ({ outputs: [] }));
    return toJob(job, outputResponse.outputs);
  }

  async approveViewSet(viewSetId: string): Promise<StudioJob> {
    return this.transitionViewSet(viewSetId, 'approve');
  }

  async retryViewSet(viewSetId: string): Promise<StudioJob> {
    return this.transitionViewSet(viewSetId, 'retry');
  }

  async createVideo(viewSetId: string): Promise<StudioVideoJob> {
    const job = await request<VideoJobResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}/video-jobs`,
      { method: 'POST' },
    );
    return toVideoJob(job);
  }

  async getVideoJob(videoJobId: string): Promise<StudioVideoJob> {
    const job = await request<VideoJobResponse>(
      `/v1/video-jobs/${encodeURIComponent(videoJobId)}`,
    );
    return toVideoJob(job);
  }
}

export const studioApi = new HttpStudioGateway();
