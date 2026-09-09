import type { ThemeConfig } from 'antd';

import {
  BG_CANVAS,
  BG_SELECTED,
  BG_SURFACE,
  BORDER,
  BORDER_RADIUS,
  BORDER_SPLIT,
  CONTROL_HEIGHT,
  PRIMARY,
  TEXT,
  TEXT_SECONDARY,
} from './tokens';

export const appTheme: ThemeConfig = {
  cssVar: { key: 'v365-render-studio' },
  token: {
    colorPrimary: PRIMARY,
    colorInfo: PRIMARY,
    colorText: TEXT,
    colorTextSecondary: TEXT_SECONDARY,
    colorBorder: BORDER,
    colorSplit: BORDER_SPLIT,
    colorBgLayout: BG_CANVAS,
    colorBgContainer: BG_SURFACE,
    borderRadius: BORDER_RADIUS,
    controlHeight: CONTROL_HEIGHT,
    fontSize: 14,
    fontFamily: "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  },
  components: {
    Button: { controlHeight: CONTROL_HEIGHT, fontWeight: 500 },
    Card: { bodyPaddingSM: 16, headerFontSizeSM: 14 },
    Form: { itemMarginBottom: 16, labelColor: TEXT_SECONDARY },
    Segmented: { itemSelectedBg: BG_SELECTED },
    Tabs: { colorBgContainer: BG_SELECTED },
  },
};
