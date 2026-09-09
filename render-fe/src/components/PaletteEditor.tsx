import { ColorPicker, Input, Space, Typography } from 'antd';

import type { MaterialPalette } from '../types/studio';

const COLORS: Array<{ key: keyof MaterialPalette; label: string }> = [
  { key: 'primary', label: 'Màu chính' },
  { key: 'secondary', label: 'Màu phụ' },
  { key: 'glass', label: 'Kính' },
  { key: 'accent', label: 'Điểm nhấn' },
  { key: 'paving', label: 'Mặt đường' },
];

interface PaletteEditorProps {
  value?: MaterialPalette;
  onChange?: (value: MaterialPalette) => void;
}

export function PaletteEditor({ value, onChange }: PaletteEditorProps) {
  if (!value) return null;

  const update = (key: keyof MaterialPalette, color: string) => {
    onChange?.({ ...value, [key]: color.toUpperCase() });
  };

  return (
    <div className="palette-grid">
      {COLORS.map(({ key, label }) => (
        <Space key={key} className="palette-row" size={8}>
          <ColorPicker
            className="palette-picker"
            aria-label={`Chọn ${label.toLowerCase()}`}
            value={value[key]}
            onChange={(_, hex) => update(key, hex)}
            showText={false}
          />
          <div className="palette-meta">
            <Typography.Text type="secondary" className="palette-label">{label}</Typography.Text>
            <Input
              className="palette-input"
              aria-label={label}
              value={value[key]}
              onChange={(event) => update(key, event.target.value)}
              maxLength={7}
            />
          </div>
        </Space>
      ))}
    </div>
  );
}
