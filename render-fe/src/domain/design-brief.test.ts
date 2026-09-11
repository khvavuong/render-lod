import { describe, expect, it } from 'vitest';

import { buildUserRenderIntent, DEFAULT_FORM_VALUES } from './design-brief';

describe('buildUserRenderIntent', () => {
  it('sends only versioned intent values and no authoritative geometry', () => {
    const intent = buildUserRenderIntent({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
      officeStoreys: 3,
      creativePrompt: 'Mặt tiền gọn và có chiều sâu.',
    });

    expect(intent.office_facade_rhythm).toBe(3);
    expect(intent.free_text).toBe('Mặt tiền gọn và có chiều sâu.');
    expect(intent.style_preset).toBe('contemporary_industrial');
    expect(intent.context_presentation).toBe('authored_only');
    expect(intent.material_palette.accent_hex).toBe('#176B4D');
    expect(intent).not.toHaveProperty('roof_ridge_orientation');
    expect(intent).not.toHaveProperty('site_design.preserve_transport_geometry');
  });
});
