import {
  CheckCircleFilled,
  ClockCircleOutlined,
  CloudSyncOutlined,
  EyeOutlined,
  FileImageOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Empty,
  Image,
  Popconfirm,
  Progress,
  Segmented,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import type {
  OutputArtifact,
  CertificationState,
  StudioJob,
  StudioVideoJob,
  VideoJobState,
  WorkflowState,
} from "../types/studio";

interface GenerationWorkspaceProps {
  job: StudioJob | null;
  videoJob: StudioVideoJob | null;
  submittingVideo: boolean;
  submittingReview: boolean;
  onGenerateVideo: () => void;
  onRefresh: () => void;
  onApprove: () => void;
  onRetry: () => void;
}

const STATE_META: Record<WorkflowState, { label: string; percent: number }> = {
  idle: { label: "Sẵn sàng", percent: 0 },
  submitting: { label: "Đang gửi yêu cầu", percent: 5 },
  resolving_model: { label: "Đang đọc mô hình", percent: 8 },
  extracting_scene: { label: "Đang trích xuất hình học", percent: 12 },
  classifying_scene: { label: "Đang phân loại mô hình", percent: 16 },
  design_planning: { label: "Đang lập phương án", percent: 20 },
  design_validation: { label: "Đang kiểm tra phương án", percent: 23 },
  needs_input: { label: "Cần bổ sung thông tin", percent: 23 },
  building_scene: { label: "Đang dựng scene", percent: 25 },
  planning_cameras: { label: "Đang lập góc nhìn", percent: 27 },
  rendering_passes: { label: "Đang dựng geometry passes", percent: 28 },
  generating_viewset: { label: "Đang tạo ảnh", percent: 58 },
  design_master_review: { label: "Chờ duyệt Design Master", percent: 48 },
  validating: { label: "Đang kiểm tra chất lượng", percent: 76 },
  human_review: { label: "Chờ duyệt thiết kế", percent: 84 },
  repairing: { label: "Đang hiệu chỉnh", percent: 67 },
  composing_board: { label: "Đang hoàn thiện đầu ra", percent: 92 },
  generating_video: { label: "Đang tạo video Veo", percent: 96 },
  completed: { label: "Đã hoàn tất", percent: 100 },
  failed: { label: "Không thành công", percent: 100 },
};

const VIDEO_STATE_LABEL: Record<VideoJobState, string> = {
  queued: "Đang chờ tạo video",
  planning: "Đang lập 6 shot",
  generating: "Đang tạo 6 shot bằng Veo",
  assembling: "Đang ghép video và chèn logo",
  completed: "Video đã hoàn tất",
  failed: "Tạo video không thành công",
};

const CERTIFICATION_META: Record<
  CertificationState,
  { label: string; color: string }
> = {
  base_pbr: { label: "PBR nền", color: "default" },
  marketing_generative_review: { label: "Ảnh AI · Chờ kiểm duyệt", color: "warning" },
  geometry_certified: { label: "Đã chứng nhận hình học", color: "processing" },
  approved_final: { label: "Đã duyệt bàn giao", color: "success" },
};

function ArtifactCard({ artifact }: { artifact: OutputArtifact }) {
  if (artifact.kind === "video") {
    return (
      <article className="artifact-card artifact-video">
        <video
          controls
          preload="metadata"
          poster=""
          aria-label={artifact.title}
        >
          <source src={artifact.url} type="video/mp4" />
        </video>
        <div className="artifact-caption">
          <Space>
            <VideoCameraOutlined />
            <Typography.Text strong>{artifact.title}</Typography.Text>
          </Space>
          <Tag bordered={false}>MP4</Tag>
        </div>
      </article>
    );
  }
  return (
    <article
      className={`artifact-card ${artifact.kind === "board" ? "artifact-board" : ""}`}
    >
      <Image
        className="artifact-image"
        src={artifact.url}
        alt={artifact.title}
        preview={{
          mask: (
            <>
              <EyeOutlined /> Xem lớn
            </>
          ),
        }}
      />
      <div className="artifact-caption">
        <Space>
          <FileImageOutlined />
          <Typography.Text strong>{artifact.title}</Typography.Text>
        </Space>
        <Tag bordered={false}>
          {artifact.kind === "board"
            ? "BOARD"
            : artifact.view_id?.toUpperCase()}
        </Tag>
      </div>
    </article>
  );
}

function EmptyCanvas() {
  return (
    <div className="empty-canvas">
      <div className="view-placeholder-grid" aria-hidden="true">
        {Array.from({ length: 6 }, (_, index) => (
          <div className="view-placeholder" key={index}>
            <span>VIEW-{String(index + 1).padStart(2, "0")}</span>
          </div>
        ))}
      </div>
      <Empty
        className="empty-state"
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Space direction="vertical" size={2}>
            <Typography.Text strong>Chưa có phiên diễn họa</Typography.Text>
            <Typography.Text type="secondary">
              Hoàn thiện thiết lập bên trái để bắt đầu tạo 6 góc nhìn.
            </Typography.Text>
          </Space>
        }
      />
    </div>
  );
}

export function GenerationWorkspace({
  job,
  videoJob,
  submittingVideo,
  submittingReview,
  onGenerateVideo,
  onRefresh,
  onApprove,
  onRetry,
}: GenerationWorkspaceProps) {
  const [filter, setFilter] = useState<"all" | "image" | "video">("all");
  const state = job?.state ?? "idle";
  const meta = STATE_META[state];
  const outputs = useMemo(
    () =>
      job?.outputs.filter(
        (item) =>
          filter === "all" ||
          item.kind === filter ||
          (filter === "image" && item.kind === "board"),
      ) ?? [],
    [filter, job],
  );
  const active = Boolean(
    job && !["completed", "failed", "human_review", "design_master_review"].includes(job.state),
  );
  const hasVideo = Boolean(job?.outputs.some((item) => item.kind === "video"));
  const videoActive = Boolean(
    videoJob && !["completed", "failed"].includes(videoJob.state),
  );
  const certification = job
    ? CERTIFICATION_META[job.certificationState]
    : null;

  return (
    <main className="generation-workspace">
      <div className="workspace-toolbar">
        <div>
          <Space size={8}>
            <Typography.Title level={4}>V365 Render Studio</Typography.Title>
            {active && <Spin size="small" />}
          </Space>
        </div>
        <Space>
          <Tag
            className={`state-tag state-${state}`}
            icon={
              state === "completed" ? (
                <CheckCircleFilled />
              ) : (
                <ClockCircleOutlined />
              )
            }
          >
            {meta.label}
          </Tag>
          {job && (
            <Button
              icon={<ReloadOutlined />}
              onClick={onRefresh}
              aria-label="Làm mới"
            >
              Làm mới
            </Button>
          )}
          {certification && (
            <Tag color={certification.color}>{certification.label}</Tag>
          )}
        </Space>
      </div>

      {job && (
        <section className="job-overview">
          <div className="progress-copy">
            <CloudSyncOutlined />
            <div>
              <Typography.Text strong>{meta.label}</Typography.Text>
              <Typography.Text type="secondary">
                View set {job.viewSetId} · Trace {job.traceId.slice(0, 12)}
              </Typography.Text>
            </div>
          </div>
          <Progress
            percent={meta.percent}
            showInfo={false}
            status={state === "failed" ? "exception" : "active"}
          />
        </section>
      )}

      {job?.state === "human_review" && (
        <Alert
          className="review-action-panel"
          type="warning"
          showIcon
          message="Bộ 6 ảnh đã được tạo và đang chờ duyệt"
          description="Một hoặc nhiều kiểm tra tự động cần con người xác nhận. Bạn vẫn có thể xem đủ ảnh bên dưới; chỉ duyệt khi hình học và thiết kế đã đạt yêu cầu."
          action={
            <Button type="primary" loading={submittingReview} onClick={onApprove}>
              Duyệt và hoàn thiện board
            </Button>
          }
        />
      )}

      {job?.state === "design_master_review" && (
        <Alert
          className="review-action-panel"
          type="info"
          showIcon
          message="Duyệt Design Master trước khi sinh toàn bộ view set"
          description="Hệ thống mới chỉ tạo một ảnh đại diện. Hãy kiểm tra ngôn ngữ facade, mái, màu vật liệu, cổng và hàng rào; chỉ khi duyệt mới phát sinh chi phí cho 5 ảnh còn lại."
          action={
            <Button type="primary" loading={submittingReview} onClick={onApprove}>
              Duyệt và tạo 5 góc còn lại
            </Button>
          }
        />
      )}

      {job?.state === "failed" && (
        <Alert
          className="review-action-panel"
          type="error"
          showIcon
          message="Pipeline gặp lỗi kỹ thuật"
          description="Các ảnh đã tạo vẫn được giữ lại. Chạy lại sẽ tiếp tục từ checkpoint gần nhất thay vì mặc định gọi lại toàn bộ dịch vụ AI."
          action={
            <Button loading={submittingReview} onClick={onRetry}>
              Tiếp tục từ checkpoint
            </Button>
          }
        />
      )}

      <div className="output-heading">
        <Segmented
          value={filter}
          onChange={(value) => setFilter(value as typeof filter)}
          options={[
            { label: "Tất cả", value: "all" },
            { label: "Hình ảnh", value: "image", icon: <FileImageOutlined /> },
            { label: "Video", value: "video", icon: <PlayCircleOutlined /> },
          ]}
        />
        {job?.state === "completed" && !hasVideo && (
          <Popconfirm
            title="Tạo video trình diễn?"
            description="Hệ thống sẽ dùng Veo tạo đủ 6 shot, sau đó tự ghép, bỏ audio và chèn logo. Thao tác này phát sinh chi phí riêng."
            okText="Tạo video"
            cancelText="Để sau"
            placement="bottomRight"
            onConfirm={onGenerateVideo}
            disabled={videoActive || submittingVideo}
          >
            <Button
              type="primary"
              icon={<VideoCameraOutlined />}
              loading={videoActive || submittingVideo}
            >
              {videoActive ? "Đang tạo video" : "Tạo video trình diễn"}
            </Button>
          </Popconfirm>
        )}
      </div>

      {videoJob && (
        <section className="video-job-status" aria-live="polite">
          <Space>
            {videoActive ? <Spin size="small" /> : <VideoCameraOutlined />}
            <Typography.Text strong>
              {VIDEO_STATE_LABEL[videoJob.state]}
            </Typography.Text>
            <Typography.Text type="secondary">
              Dự toán tối đa ${videoJob.estimatedCostUsd.toFixed(2)} · Job {videoJob.videoJobId}
            </Typography.Text>
          </Space>
        </section>
      )}

      {outputs.length ? (
        <div className="artifact-grid">
          <Image.PreviewGroup>
            {outputs.map((artifact) => (
              <ArtifactCard key={artifact.id} artifact={artifact} />
            ))}
          </Image.PreviewGroup>
        </div>
      ) : (
        <EmptyCanvas />
      )}

      {job && (
        <section className="activity-panel">
          <Typography.Title level={5}>Tiến trình pipeline</Typography.Title>
          <Timeline
            items={[
              {
                color: "green",
                children: "Design Brief đã được khóa revision",
              },
              {
                color: meta.percent >= 28 ? "green" : "gray",
                children: "Dựng conditioning passes",
              },
              {
                color: meta.percent >= 58 ? "green" : "gray",
                children: "Duyệt Design Master và tạo bộ 6 ảnh đồng nhất",
              },
              {
                color: meta.percent >= 76 ? "green" : "gray",
                children: "Geometry và consistency QA",
              },
              {
                color: meta.percent === 100 ? "green" : "gray",
                children: "Board và branding ảnh",
              },
            ]}
          />
        </section>
      )}
    </main>
  );
}
