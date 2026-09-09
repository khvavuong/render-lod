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
}

interface OutputsResponse {
  outputs: OutputArtifact[];
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(body?.detail || `Yêu cầu thất bại (${response.status})`);
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
    return toJob(job);
  }

  async getJob(viewSetId: string): Promise<StudioJob> {
    const job = await request<ViewSetResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}`,
    );
    const outputResponse = await request<OutputsResponse>(
      `/v1/view-sets/${encodeURIComponent(viewSetId)}/outputs`,
    ).catch(() => ({ outputs: [] }));
    return toJob(job, outputResponse.outputs);
  }
}

export const studioApi = new HttpStudioGateway();
