import {
  ArrowRightOutlined,
  BgColorsOutlined,
  BuildOutlined,
  BulbOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import {
  Button,
  Collapse,
  Form,
  Input,
  InputNumber,
  Segmented,
  Select,
  Space,
  Tooltip,
  Typography,
} from "antd";
import type { ReactNode } from "react";

import { DEFAULT_FORM_VALUES, STYLE_OPTIONS } from "../domain/design-brief";
import type { DesignFormValues } from "../types/studio";
import { PaletteEditor } from "./PaletteEditor";

interface DesignPanelProps {
  submitting: boolean;
  onSubmit: (values: DesignFormValues) => void;
}

const DECOR_OPTIONS = [
  { value: "minimal", label: "Tối giản" },
  { value: "subtle", label: "Nhẹ" },
  { value: "balanced", label: "Cân bằng" },
  { value: "expressive", label: "Nổi bật" },
];

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <Space size={9} className="section-title">
      {icon}
      <Typography.Text strong>{title}</Typography.Text>
    </Space>
  );
}

export function DesignPanel({ submitting, onSubmit }: DesignPanelProps) {
  const [form] = Form.useForm<DesignFormValues>();

  return (
    <aside className="design-panel">
      <div className="panel-heading">
        <Typography.Text className="panel-eyebrow">
          DESIGN BRIEF
        </Typography.Text>
        <Typography.Title level={4}>Thiết lập phương án</Typography.Title>
        <Typography.Paragraph type="secondary">
          Chọn định hướng thẩm mỹ. Hình học và quy hoạch LOD100 luôn được bảo
          toàn.
        </Typography.Paragraph>
      </div>

      <Form
        form={form}
        layout="vertical"
        initialValues={DEFAULT_FORM_VALUES}
        onFinish={onSubmit}
        requiredMark={false}
        className="design-form"
      >
        <section className="form-section">
          <SectionTitle icon={<BuildOutlined />} title="Dự án" />
          <Form.Item
            label="Mã dự án"
            name="projectId"
            extra="Tự động sử dụng model LOD100 đã xử lý gần nhất."
            rules={[
              { required: true, message: "Nhập mã dự án" },
              {
                pattern: /^[A-Za-z0-9][A-Za-z0-9._-]*$/,
                message: "Mã dự án không hợp lệ",
              },
            ]}
          >
            <Input size="large" placeholder="Ví dụ: factory-campus-01" />
          </Form.Item>
        </section>

        <section className="form-section">
          <SectionTitle icon={<SettingOutlined />} title="Ngôn ngữ kiến trúc" />
          <Form.Item label="Phong cách" name="stylePreset">
            <Select size="large" options={STYLE_OPTIONS} />
          </Form.Item>
          <Form.Item label="Mức độ chi tiết mặt đứng" name="decorLevel">
            <Segmented block options={DECOR_OPTIONS} />
          </Form.Item>
          <div className="form-grid two-columns compact-items">
            <Tooltip title="Chỉ điều khiển nhịp mặt đứng văn phòng bên trong envelope của model.">
              <Form.Item label="Số tầng văn phòng" name="officeStoreys">
                <InputNumber min={1} max={8} style={{ width: "100%" }} />
              </Form.Item>
            </Tooltip>
            <Form.Item label="Cửa xuất nhập hàng / mặt" name="loadingDocks">
              <InputNumber min={0} max={12} style={{ width: "100%" }} />
            </Form.Item>
          </div>
        </section>

        <section className="form-section">
          <SectionTitle icon={<BgColorsOutlined />} title="Màu sắc vật liệu" />
          <Form.Item name="palette">
            <PaletteEditor />
          </Form.Item>
        </section>

        <Collapse
          ghost
          className="advanced-collapse"
          items={[
            {
              key: "presentation",
              label: (
                <SectionTitle
                  icon={<BulbOutlined />}
                  title="Bối cảnh và trình bày"
                />
              ),
              children: (
                <>
                  <Form.Item label="Cảnh quan" name="landscapeCharacter">
                    <Input />
                  </Form.Item>
                  <Form.Item label="Mật độ người và xe" name="entourageDensity">
                    <Select
                      options={[
                        { value: "none", label: "Không có" },
                        { value: "low", label: "Ít" },
                        { value: "medium", label: "Vừa phải" },
                        { value: "high", label: "Nhiều" },
                      ]}
                    />
                  </Form.Item>
                  <Form.Item label="Thời điểm" name="time">
                    <Input type="time" />
                  </Form.Item>
                </>
              ),
            },
          ]}
        />

        <section className="form-section prompt-section">
          <SectionTitle icon={<BulbOutlined />} title="Yêu cầu bổ sung" />
          <Form.Item
            name="creativePrompt"
            extra="Mô tả ngắn những ưu tiên chưa có trong các lựa chọn trên."
          >
            <Input.TextArea
              rows={4}
              maxLength={1000}
              showCount
              placeholder="Ví dụ: sảnh đón chuyên nghiệp, vật liệu bền vững, ánh sáng buổi sáng tự nhiên..."
            />
          </Form.Item>
        </section>

        <div className="form-actions">
          <Button
            type="primary"
            htmlType="submit"
            size="large"
            loading={submitting}
            iconPlacement="end"
            icon={<ArrowRightOutlined />}
            block
          >
            Tạo phương án diễn họa
          </Button>
        </div>
      </Form>
    </aside>
  );
}
