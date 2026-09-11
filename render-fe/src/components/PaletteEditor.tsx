import { Alert, Button, ColorPicker, Input, Select, Space, Typography } from 'antd';
import { useEffect, useState } from 'react';

import type { MaterialPalette } from '../types/studio';

const COLORS: Array<{ key: keyof MaterialPalette; label: string; role: string }> = [
  { key: 'roof', label: 'Mái', role: 'Mái kim loại sáng, giảm hấp thụ nhiệt' },
  { key: 'primary', label: 'Thân nhà', role: 'Bao che facade chủ đạo' },
  { key: 'secondary', label: 'Kết cấu', role: 'Cột, diềm, flashing và cửa' },
  { key: 'glass', label: 'Kính', role: 'Các ô kính theo model' },
  { key: 'accent', label: 'Điểm nhấn', role: 'Lối vào và biển hiệu, dùng tiết chế' },
  { key: 'boundary', label: 'Cổng & hàng rào', role: 'Một hệ boundary trung tính, đồng nhất' },
  { key: 'paving', label: 'Mặt đường', role: 'Đường nội bộ và sân bãi' },
];

const PALETTE_PRESETS: Array<{ label: string; value: string; palette: MaterialPalette }> = [
  {
    label: 'Trung tính doanh nghiệp',
    value: 'corporate-neutral',
    palette: { roof: '#E8E7E1', primary: '#ECE9E1', secondary: '#26343D', glass: '#294B5B', accent: '#176B4D', boundary: '#626B70', paving: '#74797A' },
  },
  {
    label: 'Xanh công nghiệp',
    value: 'industrial-blue',
    palette: { roof: '#F0EFEA', primary: '#DDE2E3', secondary: '#17324D', glass: '#365B6D', accent: '#C58A2A', boundary: '#59636A', paving: '#74797A' },
  },
  {
    label: 'Graphite ấm',
    value: 'warm-graphite',
    palette: { roof: '#E8E5DE', primary: '#C9C5BB', secondary: '#34383A', glass: '#385765', accent: '#A64B2A', boundary: '#656A6D', paving: '#777B7A' },
  },
  {
    label: 'Xanh bền vững',
    value: 'sustainable-green',
    palette: { roof: '#EBEAE4', primary: '#D7DBD1', secondary: '#32453F', glass: '#365C64', accent: '#4F765C', boundary: '#626B67', paving: '#737977' },
  },
];

function rgb(hex: string): [number, number, number] {
  return [1, 3, 5].map((index) => Number.parseInt(hex.slice(index, index + 2), 16) / 255) as [number, number, number];
}

function saturation(hex: string): number {
  const [red, green, blue] = rgb(hex);
  const maximum = Math.max(red, green, blue);
  const minimum = Math.min(red, green, blue);
  return maximum === 0 ? 0 : (maximum - minimum) / maximum;
}

function luminance(hex: string): number {
  return rgb(hex)
    .map((channel) => (channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4))
    .reduce((total, channel, index) => total + channel * [0.2126, 0.7152, 0.0722][index], 0);
}

function withMaximumSaturation(hex: string, maximumSaturation: number, minimumValue = 0): string {
  const [red, green, blue] = rgb(hex);
  const maximum = Math.max(red, green, blue);
  const minimum = Math.min(red, green, blue);
  const difference = maximum - minimum;
  let hue = 0;
  if (difference > 0) {
    if (maximum === red) hue = ((green - blue) / difference) % 6;
    else if (maximum === green) hue = (blue - red) / difference + 2;
    else hue = (red - green) / difference + 4;
    hue = ((hue * 60) + 360) % 360;
  }
  const value = Math.max(maximum, minimumValue);
  const nextSaturation = Math.min(maximum === 0 ? 0 : difference / maximum, maximumSaturation);
  const chroma = value * nextSaturation;
  const section = hue / 60;
  const intermediate = chroma * (1 - Math.abs((section % 2) - 1));
  const [redPrime, greenPrime, bluePrime] =
    section < 1 ? [chroma, intermediate, 0]
      : section < 2 ? [intermediate, chroma, 0]
        : section < 3 ? [0, chroma, intermediate]
          : section < 4 ? [0, intermediate, chroma]
            : section < 5 ? [intermediate, 0, chroma]
              : [chroma, 0, intermediate];
  const offset = value - chroma;
  return `#${[redPrime, greenPrime, bluePrime]
    .map((channel) => Math.round((channel + offset) * 255).toString(16).padStart(2, '0'))
    .join('')}`.toUpperCase();
}

function balancedPalette(value: MaterialPalette): MaterialPalette {
  const competing = saturation(value.primary) > 0.65 && saturation(value.secondary) > 0.65;
  return {
    ...value,
    roof: withMaximumSaturation(value.roof, 0.16, 0.9),
    secondary: withMaximumSaturation(value.secondary, competing ? 0.35 : 0.55),
    boundary: withMaximumSaturation(value.boundary, 0.28),
  };
}

function paletteWarnings(value: MaterialPalette): string[] {
  const warnings: string[] = [];
  if (luminance(value.roof) < 0.55) warnings.push('Màu mái đang tối, dễ tạo cảm giác nặng và hấp thụ nhiệt cao.');
  if (saturation(value.secondary) > 0.72) warnings.push('Màu kết cấu quá bão hòa; nên dùng màu này làm điểm nhấn thay vì phủ cột và diềm.');
  if (saturation(value.primary) > 0.65 && saturation(value.secondary) > 0.65) warnings.push('Thân nhà và kết cấu đều quá rực, khó đạt thẩm mỹ công nghiệp tiết chế.');
  if (saturation(value.boundary) > 0.45) warnings.push('Cổng và hàng rào nên dùng màu trung tính để không cạnh tranh với công trình chính.');
  return warnings;
}

interface PaletteEditorProps {
  value?: MaterialPalette;
  onChange?: (value: MaterialPalette) => void;
}

export function PaletteEditor({ value, onChange }: PaletteEditorProps) {
  const [drafts, setDrafts] = useState<MaterialPalette | undefined>(value);

  useEffect(() => {
    setDrafts(value);
  }, [value]);

  if (!value) return null;

  const update = (key: keyof MaterialPalette, color: string) => {
    const normalized = color.toUpperCase();
    setDrafts((current) => ({ ...(current ?? value), [key]: normalized }));
    if (/^#[0-9A-F]{6}$/.test(normalized)) {
      onChange?.({ ...value, [key]: normalized });
    }
  };
  const warnings = paletteWarnings(value);
  const activePreset = PALETTE_PRESETS.find(({ palette }) =>
    COLORS.every(({ key }) => palette[key] === value[key]),
  )?.value;

  return (
    <div className="palette-editor">
      <Typography.Paragraph type="secondary" className="palette-guidance">
        Mỗi màu được khóa theo đúng vai trò vật liệu và giữ nhất quán trong cả 6 góc nhìn.
      </Typography.Paragraph>
      <Select
        className="palette-preset"
        aria-label="Phối màu gợi ý"
        placeholder="Chọn phối màu công nghiệp gợi ý"
        value={activePreset}
        options={PALETTE_PRESETS.map(({ label, value: presetValue }) => ({ label, value: presetValue }))}
        onChange={(presetValue) => {
          const preset = PALETTE_PRESETS.find(({ value: candidate }) => candidate === presetValue);
          if (preset) onChange?.(preset.palette);
        }}
      />
      <div className="material-preview" aria-label="Xem trước tỷ lệ màu vật liệu">
        <div className="material-preview-roof" style={{ backgroundColor: value.roof }} />
        <div className="material-preview-body" style={{ backgroundColor: value.primary }}>
          <span style={{ backgroundColor: value.secondary }} />
          <i style={{ backgroundColor: value.glass, borderColor: value.accent }} />
        </div>
        <div className="material-preview-boundary" style={{ borderColor: value.boundary }} />
        <div className="material-preview-paving" style={{ backgroundColor: value.paving }} />
      </div>
      {warnings.length > 0 && (
        <Alert
          className="palette-warning"
          type="warning"
          showIcon
          message="Phối màu cần cân nhắc"
          description={warnings.join(' ')}
          action={
            <Button size="small" onClick={() => onChange?.(balancedPalette(value))}>
              Tự cân bằng
            </Button>
          }
        />
      )}
      <div className="palette-grid">
        {COLORS.map(({ key, label, role }) => (
          <Space key={key} className="palette-row" size={8}>
            <ColorPicker
              className="palette-picker"
              aria-label={`Chọn ${label.toLowerCase()}`}
              value={value[key]}
              format="hex"
              disabledAlpha
              onChange={(color) => update(key, color.toHexString())}
              showText={false}
            />
            <div className="palette-meta">
              <Typography.Text className="palette-label" title={role}>
                {label}
              </Typography.Text>
              <Typography.Text type="secondary" className="palette-role" title={role}>
                {role}
              </Typography.Text>
              <Input
                className="palette-input"
                aria-label={label}
                value={drafts?.[key] ?? value[key]}
                onChange={(event) => update(key, event.target.value)}
                onBlur={() => {
                  if (!/^#[0-9A-Fa-f]{6}$/.test(drafts?.[key] ?? '')) {
                    setDrafts((current) => ({ ...(current ?? value), [key]: value[key] }));
                  }
                }}
                onPressEnter={(event) => event.currentTarget.blur()}
                status={/^#[0-9A-Fa-f]{6}$/.test(drafts?.[key] ?? '') ? undefined : 'error'}
                maxLength={7}
              />
            </div>
          </Space>
        ))}
      </div>
    </div>
  );
}
