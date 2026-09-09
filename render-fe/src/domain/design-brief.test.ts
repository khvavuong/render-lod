import { describe, expect, it } from 'vitest';

import { buildDesignBrief, DEFAULT_FORM_VALUES } from './design-brief';

describe('buildDesignBrief', () => {
  it('maps user controls into the backend contract without weakening geometry rules', () => {
    const brief = buildDesignBrief({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
      officeStoreys: 3,
      creativePrompt: 'Mặt tiền gọn và có chiều sâu.',
    });

    expect(brief.project_id).toBe('factory-01');
    expect(brief.design_preferences.requested_office_storeys).toBe(3);
    expect(brief.design_preferences.creative_prompt).toBe('Mặt tiền gọn và có chiều sâu.');
    expect(brief.site_design.preserve_transport_geometry).toBe(true);
    expect(brief.roof_ridge_orientation).toBe('long_axis');
    expect(brief.material_palette.accent_hex).toBe('#176B4D');
  });
});
