import { describe, expect, it } from 'vitest';

import { BRAND_RED, PRIMARY } from './tokens';

describe('theme tokens', () => {
  it('keeps the action colour separate from the destructive brand colour', () => {
    expect(PRIMARY).toBe('#1677ff');
    expect(BRAND_RED).toBe('#E3212C');
    expect(PRIMARY).not.toBe(BRAND_RED);
  });
});
