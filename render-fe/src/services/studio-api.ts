import { buildDesignBrief } from '../domain/design-brief';
import type {
  DesignFormValues,
  OutputArtifact,
  StudioGateway,
  StudioJob,
  WorkflowState,
} from '../types/studio';

interface DesignRevisionResponse {
  design_revision: string;
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
  error_message?: string | null;
}

interface OutputsResponse {
  outputs: OutputArtifact[];
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

function toJob(job: ViewSetResponse, outputs: OutputArtifact[] = []): StudioJob {
  return {
    jobId: job.job_id,
    traceId: job.trace_id,
    viewSetId: job.view_set_id,
    designRevision: job.design_revision,
    state: job.state,
    outputs,
    errorMessage: job.error_message ?? undefined,
  };
}

export class HttpStudioGateway implements StudioGateway {
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
        `Model đã tải lên nhưng chưa được xử lý. Chạy APS extraction cho revision ${model.model_revision} trước khi tạo ảnh.`,
      );
    }
    const revision = await request<DesignRevisionResponse>(
      `/v1/projects/${encodeURIComponent(values.projectId)}/design-revisions`,
      {
        method: 'POST',
        body: JSON.stringify({
          model_revision: model.model_revision,
          brief: buildDesignBrief(values),
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
        }),
      },
    );
    if (job.state !== 'completed') {
      return toJob(job);
    }
    const outputResponse = await request<OutputsResponse>(
      `/v1/view-sets/${encodeURIComponent(job.view_set_id)}/outputs`,
    );
    return toJob(job, outputResponse.outputs);
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
}

export const studioApi = new HttpStudioGateway();
