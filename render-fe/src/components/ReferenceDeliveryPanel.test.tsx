import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { referenceAction } from '../services/studio-api';
import type { StudioJob } from '../types/studio';
import { ReferenceDeliveryPanel } from './ReferenceDeliveryPanel';

vi.mock('../services/studio-api', () => ({ referenceAction: vi.fn() }));
const job: StudioJob = { jobId: 'job', traceId: 'trace', viewSetId: 'views', designRevision: 'design',
  state: 'design_master_review', certificationState: 'marketing_generative_review',
  generationPolicy: 'reference-led-proposal-v1', outputs: [] };
const empty = { design: null, ranking: null, selection: null, qa: null, delivery_review: null,
  generation_calls_reserved: 2 };
beforeEach(() => vi.mocked(referenceAction).mockReset());
afterEach(cleanup);

describe('reference-led delivery controls', () => {
  it('requires a reviewer and registers the selected branch without generating images', async () => {
    vi.mocked(referenceAction).mockResolvedValue(empty);
    render(<ReferenceDeliveryPanel job={job} onRefresh={vi.fn()} />);
    const button = await screen.findByRole('button', { name: 'Đăng ký hướng thiết kế' });
    expect(button).toBeDisabled();
    fireEvent.change(screen.getByPlaceholderText('Tên người duyệt'), { target: { value: 'client' } });
    fireEvent.click(button);
    await waitFor(() => expect(referenceAction).toHaveBeenCalledWith('views', 'design-registration',
      { anchor: 'site', reviewer: 'client', design_notes: '' }));
    expect(vi.mocked(referenceAction).mock.calls.some(c => c[1] === 'registered-generation')).toBe(false);
  });

  it('never enables delivery approval merely because integrity QA exists', async () => {
    vi.mocked(referenceAction).mockResolvedValue({ ...empty, design: { master_family_id: 'family' },
      qa: { artifact_integrity: 'pass', consistency: 'unknown' } });
    render(<ReferenceDeliveryPanel job={{ ...job, state: 'human_review' }} onRefresh={vi.fn()} />);
    expect(await screen.findByRole('button', { name: 'Duyệt marketing theo phạm vi đã đối chiếu' })).toBeDisabled();
    expect(referenceAction).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole('button', { name: /Generate sáu ảnh/ })).not.toBeInTheDocument();
  });

  it('displays a marketing review without claiming 3D certification', async () => {
    vi.mocked(referenceAction).mockResolvedValue({ ...empty, design: { master_family_id: 'family' },
      delivery_review: { delivery_approved: true } });
    render(<ReferenceDeliveryPanel job={{ ...job, state: 'completed' }} onRefresh={vi.fn()} />);
    expect(await screen.findByText(/Đã duyệt marketing theo review; không phải chứng nhận/)).toBeInTheDocument();
  });
});
