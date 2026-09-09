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

  it('creates an immutable design revision before requesting the view set', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ model_revision: 'model-revision-01' }))
      .mockResolvedValueOnce(jsonResponse({ design_revision: 'R01-design' }, 201))
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
      );
    vi.stubGlobal('fetch', fetchMock);

    const result = await new HttpStudioGateway().createDesign({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
    });

    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(fetchMock.mock.calls[0][0]).toBe('/v1/models/latest');
    expect(fetchMock.mock.calls[1][0]).toBe('/v1/projects/factory-01/design-revisions');
    const firstRequest = fetchMock.mock.calls[1][1] as RequestInit;
    const payload = JSON.parse(firstRequest.body as string) as {
      model_revision: string;
      brief: { site_design: { preserve_transport_geometry: boolean } };
    };
    expect(payload.model_revision).toBe('model-revision-01');
    expect(payload.brief.site_design.preserve_transport_geometry).toBe(true);
    expect(fetchMock.mock.calls[2][0]).toBe('/v1/design-revisions/R01-design/view-sets');
    expect(result).toMatchObject({
      jobId: 'job-01',
      viewSetId: 'viewset-01',
      state: 'rendering_passes',
    });
  });
});
