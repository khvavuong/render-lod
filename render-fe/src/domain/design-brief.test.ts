import { describe, expect, it } from 'vitest';

import { buildUserRenderIntent, DEFAULT_FORM_VALUES } from './design-brief';

describe('buildUserRenderIntent', () => {
  it('sends only versioned intent values and no authoritative geometry', () => {
    const intent = buildUserRenderIntent({
      ...DEFAULT_FORM_VALUES,
      projectId: 'factory-01',
      officeEntranceKit: 'framed_glazed_bay',
      creativePrompt: 'Mặt tiền gọn và có chiều sâu.',
    });

    expect(intent.office_entrance_kit).toBe('framed_glazed_bay');
    expect(intent.free_text).toBe('Mặt tiền gọn và có chiều sâu.');
    expect(intent.design_package).toBe('premium_practical');
    expect(intent.facade_rhythm_kit).toBe('mixed_restrained');
    expect(intent.material_palette.accent_hex).toBe('#176B4D');
    expect(intent).not.toHaveProperty('roof_ridge_orientation');
    expect(intent).not.toHaveProperty('site_design.preserve_transport_geometry');
  });

  it('preserves all custom material colors in their semantic roles', () => {
    const intent = buildUserRenderIntent({
      ...DEFAULT_FORM_VALUES,
      palette: {
        roof: '#F0EFEA',
                primary: '#D45500',
        secondary: '#17324D',
        glass: '#547789',
        accent: '#C9A227',
        boundary: '#59636A',
        paving: '#6B6F72',
      },
    });

    expect(intent.material_palette).toEqual({
      roof_hex: '#F0EFEA',
      primary_hex: '#D45500',
      secondary_hex: '#17324D',
      glass_hex: '#547789',
      accent_hex: '#C9A227',
      boundary_hex: '#59636A',
      paving_hex: '#6B6F72',
    });
  });
});
