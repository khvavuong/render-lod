import {
  ArrowRightOutlined,
  BgColorsOutlined,
  BuildOutlined,
  BulbOutlined,
  CloudUploadOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import {
  Button,
  Card,
  Collapse,
  Flex,
  Form,
  Input,
  InputNumber,
  Segmented,
  Select,
  Space,
  Typography,
  Upload,
} from "antd";
import type { UploadFile } from "antd";
import type { ReactNode } from "react";
import { useState } from "react";

import { DEFAULT_FORM_VALUES, STYLE_OPTIONS } from "../domain/design-brief";
import type { DesignFormValues } from "../types/studio";
import { PaletteEditor } from "./PaletteEditor";

interface DesignPanelProps {
  submitting: boolean;
  onSubmit: (values: DesignFormValues) => void;
}

const MAX_RVT_FILE_BYTES = 2 * 1024 * 1024 * 1024;

const DECOR_OPTIONS = [
  { value: "minimal", label: "Tối giản" },
  { value: "subtle", label: "Nhẹ" },
  { value: "balanced", label: "Cân bằng" },
  { value: "expressive", label: "Nổi bật" },
];

const ENTOURAGE_OPTIONS = [
  { value: "none", label: "Không có" },
  { value: "low", label: "Ít" },
  { value: "medium", label: "Vừa phải" },
  { value: "high", label: "Nhiều" },
];

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return (
    <Space size={8} className="section-title">
      {icon}
      <Typography.Text strong>{title}</Typography.Text>
    </Space>
  );
}

export function DesignPanel({ submitting, onSubmit }: DesignPanelProps) {
  const [form] = Form.useForm<DesignFormValues>();
  const [modelFiles, setModelFiles] = useState<UploadFile[]>([]);
  const [modelError, setModelError] = useState<string>();

  const handleSubmit = (values: DesignFormValues) => {
    const modelFile = modelFiles[0]?.originFileObj;
    if (!modelFile) {
      setModelError("Chọn một file Revit trước khi tạo phương án");
      return;
    }
    setModelError(undefined);
    onSubmit({
      ...DEFAULT_FORM_VALUES,
      ...values,
      palette: {
        ...DEFAULT_FORM_VALUES.palette,
        ...values.palette,
      },
      modelFile,
    });
  };

  return (
    <aside className="design-panel">
      <Form
        form={form}
        layout="vertical"
        initialValues={DEFAULT_FORM_VALUES}
        onFinish={handleSubmit}
        requiredMark={false}
        className="design-form"
      >
        <Flex vertical gap={16}>
          <Card
            size="small"
            title={
              <SectionTitle icon={<BuildOutlined />} title="Thông tin dự án" />
            }
          >
            <Form.Item
              label="LOD 100"
              validateStatus={modelError ? "error" : undefined}
              help={modelError}
              required
            >
              <Upload.Dragger
                accept=".rvt"
                beforeUpload={(file) => {
                  if (!file.name.toLowerCase().endsWith(".rvt")) {
                    setModelError("Chỉ hỗ trợ định dạng .rvt");
                    return Upload.LIST_IGNORE;
                  }
                  if (file.size > MAX_RVT_FILE_BYTES) {
                    setModelError("Dung lượng file không được vượt quá 2 GiB");
                    return Upload.LIST_IGNORE;
                  }
                  setModelError(undefined);
                  return false;
                }}
                fileList={modelFiles}
                maxCount={1}
                multiple={false}
                onChange={({ fileList }) => setModelFiles(fileList.slice(-1))}
              >
                <Flex vertical align="center" gap={2}>
                  <CloudUploadOutlined className="upload-icon" />
                  <Typography.Text italic>Upload file</Typography.Text>
                </Flex>
              </Upload.Dragger>
            </Form.Item>
            <Form.Item
              label="Mã dự án"
              name="projectId"
              rules={[
                { required: true, message: "Nhập mã dự án" },
                {
                  pattern: /^[A-Za-z0-9][A-Za-z0-9._-]*$/,
                  message:
                    "Chỉ dùng chữ, số, dấu chấm, gạch ngang hoặc gạch dưới",
                },
              ]}
            >
              <Input placeholder="Ví dụ: factory-campus-01" />
            </Form.Item>
          </Card>

          <Card
            size="small"
            title={
              <SectionTitle
                icon={<SettingOutlined />}
                title="Định hướng kiến trúc"
              />
            }
          >
            <Form.Item label="Phong cách" name="stylePreset">
              <Select options={STYLE_OPTIONS} />
            </Form.Item>
            <Form.Item label="Mức độ chi tiết mặt đứng" name="decorLevel">
              <Segmented block options={DECOR_OPTIONS} />
            </Form.Item>
            <Flex gap={16}>
              <Form.Item
                className="flex-field"
                label="Số tầng"
                name="officeStoreys"
                tooltip="Điều khiển nhịp mặt đứng trong envelope của model."
              >
                <InputNumber min={1} max={8} className="full-width-control" />
              </Form.Item>
              <Form.Item
                className="flex-field"
                label="Cửa xuất nhập hàng"
                name="loadingDocks"
              >
                <InputNumber min={0} max={12} className="full-width-control" />
              </Form.Item>
            </Flex>
          </Card>

          <Card
            size="small"
            title={
              <SectionTitle
                icon={<BgColorsOutlined />}
                title="Bảng màu vật liệu"
              />
            }
          >
            <Form.Item name="palette" className="last-form-item">
              <PaletteEditor />
            </Form.Item>
          </Card>

          <Collapse
            items={[
              {
                key: "presentation",
                forceRender: true,
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
                    <Form.Item
                      label="Mật độ người và xe"
                      name="entourageDensity"
                    >
                      <Select options={ENTOURAGE_OPTIONS} />
                    </Form.Item>
                    <Form.Item
                      label="Thời điểm"
                      name="time"
                      className="last-form-item"
                    >
                      <Input type="time" />
                    </Form.Item>
                  </>
                ),
              },
            ]}
          />

          <Card
            size="small"
            title={
              <SectionTitle icon={<BulbOutlined />} title="Yêu cầu bổ sung" />
            }
          >
            <Form.Item name="creativePrompt" className="last-form-item">
              <Input.TextArea
                rows={3}
                maxLength={1000}
                showCount
                placeholder="Mô tả ngắn những yêu cầu chưa có trong các lựa chọn trên."
              />
            </Form.Item>
          </Card>
        </Flex>

        <Flex vertical gap={8} className="form-actions">
          <Button
            type="primary"
            htmlType="submit"
            loading={submitting}
            icon={<ArrowRightOutlined />}
            block
          >
            Tạo phương án diễn họa
          </Button>
        </Flex>
      </Form>
    </aside>
  );
}
