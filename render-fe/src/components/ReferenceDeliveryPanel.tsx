import { Alert, Button, Checkbox, Image, Input, Popconfirm, Select, Space, Typography } from 'antd';
import { useCallback, useEffect, useState } from 'react';

import { referenceAction } from '../services/studio-api';
import type { StudioJob } from '../types/studio';

interface Candidate {
  candidate_id: string;
  camera: { role: string; view_id: string };
  score: number;
  measurement: { feasible: boolean };
}
interface Progress {
  design: { master_family_id: string } | null;
  ranking: { candidates: Candidate[]; suggested_ids: string[] } | null;
  selection: { shots: { candidate_id: string; view_id: string; camera: { role: string } }[] } | null;
  qa: unknown;
  delivery_review: { delivery_approved: boolean } | null;
  advisory_review?: { delivery_recommended: boolean; summary: string };
  generation_calls_reserved: number;
}
const checks = {
  architecture: 'Kiến trúc đạt yêu cầu', realism: 'Vật liệu/ánh sáng chân thực',
  consistency: 'Sáu ảnh cùng một thiết kế', vietnam_context: 'Bối cảnh nhà xưởng Việt Nam phù hợp',
  source_requirements: 'Đã đối chiếu yêu cầu/source theo phạm vi ảnh',
  camera_fidelity: 'Đã đối chiếu bố cục ảnh với camera preview',
};

export function ReferenceDeliveryPanel({ job, onRefresh }: { job: StudioJob; onRefresh: () => void }) {
  const [progress, setProgress] = useState<Progress | null>(null);
  const [anchor, setAnchor] = useState('site');
  const [reviewer, setReviewer] = useState('');
  const [notes, setNotes] = useState('');
  const [ids, setIds] = useState<string[]>([]);
  const [approved, setApproved] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const result = await referenceAction<Progress>(job.viewSetId, 'reference-progress');
      setProgress(result);
      setIds(result.ranking?.suggested_ids ?? []);
    } catch (reason) { setError(String(reason)); }
  }, [job.viewSetId]);
  useEffect(() => { void load(); }, [load, job.state]);
  async function act(action: string, body: unknown) {
    setBusy(true); setError(null);
    try {
      await referenceAction(job.viewSetId, action, body);
      await load(); onRefresh();
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  }
  const roles = [...new Set(progress?.ranking?.candidates.map(c => c.camera.role) ?? [])];
  return <section className="activity-panel">
    <Typography.Title level={5}>Reference-led · Thiết kế → Camera → Bộ ảnh → Review</Typography.Title>
    <Alert type="info" showIcon message="Mỗi phương án có thiết kế và lineage riêng"
      description="Không biến proposal đã chọn thành mẫu mặc định cho dự án khác. Mặt khuất và công năng chưa duyệt vẫn chưa xác định. Preview source không chứng minh ảnh AI giữ đúng geometry." />
    {error && <Alert type="error" message={error} />}
    {progress?.advisory_review?.delivery_recommended === false && <Alert type="warning"
      message="Đánh giá advisory: chưa đề xuất bàn giao" description={progress.advisory_review.summary} />}
    <Space direction="vertical" style={{ width: '100%', marginTop: 12 }}>
      <Input placeholder="Tên người duyệt" value={reviewer} onChange={e => setReviewer(e.target.value)} />
      <Input.TextArea placeholder="Yêu cầu/định hướng thiết kế, hoặc ghi nhận đối chiếu từng ảnh khi duyệt bộ ảnh"
        value={notes} onChange={e => setNotes(e.target.value)} rows={3} />
      {!progress?.design && job.state === 'design_master_review' && <Space>
        <Select value={anchor} onChange={setAnchor} options={[
          { value: 'site', label: 'Proposal tổng thể' }, { value: 'facade', label: 'Proposal văn phòng' },
        ]} />
        <Button loading={busy} disabled={!reviewer.trim()} onClick={() => void act('design-registration',
          { anchor, reviewer, design_notes: notes })}>Đăng ký hướng thiết kế</Button>
      </Space>}
      {progress?.design && <Typography.Text>Family: {progress.design.master_family_id}</Typography.Text>}
      {progress?.design && !progress.ranking && job.state === 'design_master_review' &&
        <Button loading={busy} onClick={() => void act('shots/search', {})}>Tìm camera và render preview source</Button>}
      {progress?.ranking && job.state === 'design_master_review' && <>
        <Typography.Text>Xem contact sheet bên dưới; chọn một candidate cho mỗi mục đích ảnh.</Typography.Text>
        {roles.map(role => <Space key={role}>
          <Typography.Text>{role}</Typography.Text>
          <Select style={{ width: 380 }} value={ids.find(id => progress.ranking?.candidates
            .some(c => c.candidate_id === id && c.camera.role === role))}
            options={progress.ranking?.candidates.filter(c => c.camera.role === role)
              .map(c => ({ value: c.candidate_id, label: `${c.camera.view_id} · ${c.score.toFixed(2)}`,
                disabled: !c.measurement.feasible || c.score <= 0 }))}
            onChange={id => setIds(current => [...current.filter(old => !progress.ranking?.candidates
              .some(c => c.candidate_id === old && c.camera.role === role)), id])} />
        </Space>)}
        <Button loading={busy} disabled={ids.length !== 6} onClick={() => void act('shots/select',
          { candidate_ids: ids })}>Lưu sáu shot</Button>
        {Boolean(progress.selection) && <Popconfirm title="Sinh bộ sáu ảnh?"
          description="Tối đa sáu lượt generate trả phí. Không tự retry hoặc tự duyệt bàn giao."
          onConfirm={() => void act('registered-generation', {})}>
          <Button type="primary" loading={busy}>Generate sáu ảnh theo thiết kế đã chọn</Button>
        </Popconfirm>}
      </>}
      {Boolean(progress?.qa) && job.state === 'human_review' && <>
        <Typography.Text>Đối chiếu từng cặp: geometry preview bên trái, output AI bên phải.</Typography.Text>
        <Image.PreviewGroup>
          {progress?.selection?.shots.map(shot => <Space key={shot.view_id} wrap>
            <Typography.Text>{shot.camera.role}</Typography.Text>
            <Image width={280} alt={`Source-only ${shot.camera.role}`} src={`/v1/view-sets/${encodeURIComponent(job.viewSetId)}/shots/previews/${encodeURIComponent(shot.candidate_id)}`} />
            <Image width={280} alt={`AI ${shot.camera.role}`} src={`/v1/view-sets/${encodeURIComponent(job.viewSetId)}/outputs/registered-${shot.view_id}`} />
          </Space>)}
        </Image.PreviewGroup>
        <Checkbox.Group options={Object.entries(checks).map(([value, label]) => ({ value, label }))}
          value={approved} onChange={setApproved} />
        <Button type="primary" loading={busy} disabled={approved.length !== 6 || notes.trim().length < 20 || !reviewer.trim()}
          onClick={() => void act('delivery-review', { reviewer, decision: 'approve', evidence_notes: notes,
            ...Object.fromEntries(Object.keys(checks).map(key => [key, approved.includes(key)])) })}>
          Duyệt marketing theo phạm vi đã đối chiếu</Button>
        <Button loading={busy} disabled={notes.trim().length < 20 || !reviewer.trim()}
          onClick={() => void act('delivery-review', { reviewer, decision: 'reject', evidence_notes: notes,
            ...Object.fromEntries(Object.keys(checks).map(key => [key, approved.includes(key)])) })}>
          Không đạt · Lưu đánh giá</Button>
      </>}
      {progress?.delivery_review?.delivery_approved && <Alert type="success"
        message="Đã duyệt marketing theo review; không phải chứng nhận kích thước 3D" />}
      <Typography.Text type="secondary">Lượt gọi đã reserve: {progress?.generation_calls_reserved ?? 0}. Legacy vẫn là mặc định.</Typography.Text>
    </Space>
  </section>;
}
