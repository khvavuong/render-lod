import { afterEach, describe, expect, it, vi } from 'vitest';

import { DEFAULT_FORM_VALUES } from '../domain/design-brief';
import { HttpStudioGateway } from './studio-api';

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('HttpStudioGateway', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('loads the versioned design option catalog from the backend', async () => {
    const options = {
      schema_version: '1.0.0',
      catalog_version: 'industrial-intent-v1',
      styles: [],
      decor_levels: [],
      landscapes: [],
      creative_budgets: [],
      loading_dock_policies: [],
      context_presentations: [],
      realism_presets: [],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(options));
    vi.stubGlobal('fetch', fetchMock);

    await expect(new HttpStudioGateway().getDesignOptions()).resolves.toEqual(options);
    expect(fetchMock).toHaveBeenCalledWith('/v1/design-options', expect.anything());
  });

  it('creates an immutable design revision before requesting the view set', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse(
          {
            model_revision: 'model-revision-01',
            file_name: 'factory.rvt',
            size_bytes: 12,
            ready: true,
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            design_revision: 'R01-design',
            warnings: [
              {
                code: 'loading_dock_requires_design_review',
                field: 'loading_dock_count',
                message: 'Cần duyệt vị trí cửa.',
              },
            ],
          },
          201,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse(
          {
            job_id: 'job-01',
            trace_id: 'trace-01',
            view_set_id: 'viewset-01',
            design_revision: 'R01-design',
            state: 'rendering_passes',
          },
          202,
        ),
      )
      .mockResolvedValueOnce(jsonResponse({ outputs: [] }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await new HttpStudioGateway().createDesign({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
      modelFile: new File(['rvt-content'], 'factory.rvt'),
    });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[0][0]).toBe('/v1/models');
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(fetchMock.mock.calls[1][0]).toBe('/v1/projects/factory-01/design-revisions');
    const firstRequest = fetchMock.mock.calls[1][1] as RequestInit;
    const payload = JSON.parse(firstRequest.body as string) as {
      model_revision: string;
      intent: { style_preset: string; context_presentation: string };
    };
    expect(payload.model_revision).toBe('model-revision-01');
    expect(payload.intent.style_preset).toBe('contemporary_industrial');
    expect(payload.intent.context_presentation).toBe('authored_only');
    expect(fetchMock.mock.calls[2][0]).toBe('/v1/design-revisions/R01-design/view-sets');
    expect(fetchMock.mock.calls[3][0]).toBe('/v1/view-sets/viewset-01/outputs');
    expect(result).toMatchObject({
      jobId: 'job-01',
      viewSetId: 'viewset-01',
      state: 'rendering_passes',
      intentWarnings: [{ code: 'loading_dock_requires_design_review' }],
    });
  });

  it('publishes cached images even when an idempotent job is already failed', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ model_revision: 'model-revision-01', ready: true }, 201),
      )
      .mockResolvedValueOnce(jsonResponse({ design_revision: 'R01-design' }, 201))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            job_id: 'job-01',
            trace_id: 'trace-01',
            view_set_id: 'viewset-01',
            design_revision: 'R01-design',
            state: 'failed',
            error_message: 'legacy QA failure',
          },
          202,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          outputs: [
            {
              id: 'image-view-01',
              kind: 'image',
              title: 'VIEW-01',
              url: '/v1/view-sets/viewset-01/outputs/image-view-01',
            },
          ],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await new HttpStudioGateway().createDesign({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
      modelFile: new File(['rvt-content'], 'factory.rvt'),
    });

    expect(result.state).toBe('failed');
    expect(result.outputs).toHaveLength(1);
    expect(fetchMock.mock.calls[3][0]).toBe('/v1/view-sets/viewset-01/outputs');
  });

  it('resumes review actions and keeps current outputs visible', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          job_id: 'job-01',
          trace_id: 'trace-01',
          view_set_id: 'viewset-01',
          design_revision: 'R01-design',
          state: 'composing_board',
        }, 202),
      )
      .mockResolvedValueOnce(jsonResponse({ outputs: [{ id: 'image-view-01', kind: 'image' }] }));
    vi.stubGlobal('fetch', fetchMock);

    const result = await new HttpStudioGateway().approveViewSet('viewset-01');

    expect(fetchMock.mock.calls[0][0]).toBe('/v1/view-sets/viewset-01/approve');
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(result.state).toBe('composing_board');
    expect(result.outputs).toHaveLength(1);
  });

  it('formats FastAPI validation errors for the alert', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        jsonResponse(
          {
            detail: [
              {
                type: 'greater_than_equal',
                loc: ['body', 'intent', 'office_facade_rhythm'],
                msg: 'Input should be greater than or equal to 0.25',
              },
            ],
          },
          422,
        ),
      ),
    );

    await expect(
      new HttpStudioGateway().createDesign({
        ...DEFAULT_FORM_VALUES,
        projectId: 'factory-01',
        modelFile: new File(['rvt-content'], 'factory.rvt'),
      }),
    ).rejects.toThrow(
      'Dữ liệu chưa hợp lệ: intent.office_facade_rhythm: Input should be greater than or equal to 0.25',
    );
  });

  it('explains how to recover when the API is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));

    await expect(
      new HttpStudioGateway().createDesign({
        ...DEFAULT_FORM_VALUES,
        projectId: 'factory-01',
        modelFile: new File(['rvt-content'], 'factory.rvt'),
      }),
    ).rejects.toThrow('make api');
  });

  it('loads outputs immediately for an idempotent completed job', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ model_revision: 'model-revision-01', ready: true }, 201),
      )
      .mockResolvedValueOnce(jsonResponse({ design_revision: 'R01-design' }, 201))
      .mockResolvedValueOnce(
        jsonResponse(
          {
            job_id: 'job-01',
            trace_id: 'trace-01',
            view_set_id: 'viewset-01',
            design_revision: 'R01-design',
            state: 'completed',
          },
          202,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          outputs: [
            {
              id: 'image-view-01',
              kind: 'image',
              title: 'VIEW-01',
              url: '/v1/view-sets/viewset-01/outputs/image-view-01',
            },
          ],
        }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await new HttpStudioGateway().createDesign({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
      modelFile: new File(['rvt-content'], 'factory.rvt'),
    });

    expect(fetchMock).toHaveBeenCalledTimes(4);
    expect(fetchMock.mock.calls[3][0]).toBe('/v1/view-sets/viewset-01/outputs');
    expect(result.outputs).toHaveLength(1);
  });

  it('starts video through a separate opt-in endpoint', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse(
        {
          video_job_id: 'video-job-01',
          view_set_id: 'viewset-01',
          state: 'queued',
          created: true,
          estimated_cost_usd: 1.2,
          output_url: null,
        },
        202,
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const result = await new HttpStudioGateway().createVideo('viewset-01');

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe('/v1/view-sets/viewset-01/video-jobs');
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST');
    expect(result).toMatchObject({
      videoJobId: 'video-job-01',
      state: 'queued',
      estimatedCostUsd: 1.2,
    });
  });
});
