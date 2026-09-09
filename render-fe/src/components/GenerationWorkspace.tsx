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
  Progress,
  Segmented,
  Space,
  Spin,
  Tag,
  Timeline,
  Typography,
} from "antd";
import { useMemo, useState } from "react";

import type { OutputArtifact, StudioJob, WorkflowState } from "../types/studio";

interface GenerationWorkspaceProps {
  job: StudioJob | null;
  error: string | null;
  onRefresh: () => void;
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
  validating: { label: "Đang kiểm tra chất lượng", percent: 76 },
  human_review: { label: "Chờ duyệt thiết kế", percent: 84 },
  repairing: { label: "Đang hiệu chỉnh", percent: 67 },
  composing_board: { label: "Đang hoàn thiện đầu ra", percent: 92 },
  completed: { label: "Đã hoàn tất", percent: 100 },
  failed: { label: "Không thành công", percent: 100 },
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
          <Tag variant="filled">MP4</Tag>
        </div>
      </article>
    );
  }
  return (
    <article
      className={`artifact-card ${artifact.kind === "board" ? "artifact-board" : ""}`}
    >
      <Image
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
        <Tag variant="filled">
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
        image={Empty.PRESENTED_IMAGE_SIMPLE}
        description={
          <Space orientation="vertical" size={2}>
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
  error,
  onRefresh,
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
  const active = Boolean(job && !["completed", "failed"].includes(job.state));

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
        </Space>
      </div>

      {error && (
        <Alert
          showIcon
          type="error"
          message="Không thể tiếp tục"
          description={error}
        />
      )}

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
      </div>

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
                children: "Tạo bộ 6 ảnh đồng nhất",
              },
              {
                color: meta.percent >= 76 ? "green" : "gray",
                children: "Geometry và consistency QA",
              },
              {
                color: meta.percent === 100 ? "green" : "gray",
                children: "Board, branding và showreel",
              },
            ]}
          />
        </section>
      )}
    </main>
  );
}
