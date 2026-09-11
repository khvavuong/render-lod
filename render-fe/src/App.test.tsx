import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import App from './App';
import type { StudioGateway } from './types/studio';

const gateway: StudioGateway = {
  prepareModel: async () => { throw new Error('not called'); },
  previewDesign: async () => { throw new Error('not called'); },
  createDesign: async () => { throw new Error('not called'); },
  getJob: async () => { throw new Error('not called'); },
  approveViewSet: async () => { throw new Error('not called'); },
  rejectDesignMaster: async () => { throw new Error('not called'); },
  retryViewSet: async () => { throw new Error('not called'); },
  createVideo: async () => { throw new Error('not called'); },
  getVideoJob: async () => { throw new Error('not called'); },
};

describe('V365 Render Studio', () => {
  it('renders the two-panel configuration and generation workspace', () => {
    render(<App gateway={gateway} />);

    expect(screen.getByText('01 · Nguồn mô hình')).toBeInTheDocument();
    expect(screen.getByText('V365 Render Studio')).toBeInTheDocument();
    expect(screen.getByLabelText('Mã dự án')).toBeInTheDocument();
    expect(screen.getByText('03 · Vật liệu và màu')).toBeInTheDocument();
    expect(screen.queryByLabelText('Model revision')).not.toBeInTheDocument();
    expect(screen.queryByText('Độ dốc mái')).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText(/Chỉ mô tả ưu tiên/)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Phân tích model/ })).toBeInTheDocument();
  });
});
