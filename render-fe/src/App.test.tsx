import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from './App';
import type { StudioGateway } from './types/studio';

const gateway: StudioGateway = {
  createDesign: async () => { throw new Error('not called'); },
  getJob: async () => { throw new Error('not called'); },
};

describe('V365 Render Studio', () => {
  it('renders the two-panel configuration and generation workspace', () => {
    render(<App gateway={gateway} />);

    expect(screen.getByText('Thông tin dự án')).toBeInTheDocument();
    expect(screen.getByText('V365 Render Studio')).toBeInTheDocument();
    expect(screen.getByLabelText('Mã dự án')).toBeInTheDocument();
    expect(screen.getByText('Bảng màu vật liệu')).toBeInTheDocument();
    expect(screen.queryByLabelText('Model revision')).not.toBeInTheDocument();
    expect(screen.queryByText('Độ dốc mái')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Mô tả ngắn/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Tạo phương án/ })).toBeInTheDocument();
  });
});
