import {
  ArrowRightOutlined,
  BgColorsOutlined,
  BuildOutlined,
  CheckCircleFilled,
  CloudUploadOutlined,
  EyeOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Collapse,
  Flex,
  Form,
  Input,
  Segmented,
  Select,
  Space,
  Steps,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { UploadFile } from 'antd';
import type { ReactNode } from 'react';
import { useMemo, useState } from 'react';

import { DEFAULT_FORM_VALUES } from '../domain/design-brief';
import type {
  DesignFormValues,
  DesignOption,
  DesignOptions,
  DesignPreview,
  PreparedModel,
} from '../types/studio';
import { PaletteEditor } from './PaletteEditor';

interface DesignPanelProps {
  submitting: boolean;
  preparingModel: boolean;
  previewingDesign: boolean;
  preparedModel: PreparedModel | null;
  designPreview: DesignPreview | null;
  designOptions: DesignOptions;
  onPrepareModel: (file: File) => void;
  onPreview: (values: DesignFormValues) => void;
  onIntentChange: () => void;
  onModelChange: () => void;
  onSubmit: (values: DesignFormValues) => void;
}

const MAX_RVT_FILE_BYTES = 2 * 1024 * 1024 * 1024;

function SectionTitle({ icon, title }: { icon: ReactNode; title: string }) {
  return <Space size={8} className="section-title">{icon}<Typography.Text strong>{title}</Typography.Text></Space>;
}

export function DesignPanel(props: DesignPanelProps) {
  const {
    submitting, preparingModel, previewingDesign, preparedModel, designPreview,
    designOptions, onPrepareModel, onPreview, onIntentChange, onModelChange, onSubmit,
  } = props;
  const [form] = Form.useForm<DesignFormValues>();
  const [modelFiles, setModelFiles] = useState<UploadFile[]>([]);
  const [modelError, setModelError] = useState<string>();
  const capabilities = useMemo(
    () => new Map(preparedModel?.capabilities.components.map((item) => [item.key, item]) ?? []),
    [preparedModel],
  );

  const constrainedOptions = (items: DesignOption[]) => items.map((item) => ({
    ...item,
    disabled: Boolean(item.requires_capability && !capabilities.get(item.requires_capability)?.supported),
    label: item.requires_capability && !capabilities.get(item.requires_capability)?.supported
      ? `${item.label} · model chưa hỗ trợ`
      : item.label,
  }));

  const currentStep = designPreview ? 2 : preparedModel ? 1 : 0;

  const modelFile = () => modelFiles[0]?.originFileObj;

  const handlePrepare = () => {
    const file = modelFile();
    if (!file) {
      setModelError('Chọn một file Revit trước khi phân tích');
      return;
    }
    setModelError(undefined);
    onPrepareModel(file);
  };

  const handleFinish = (values: DesignFormValues) => {
    const file = modelFile();
    if (!file) {
      setModelError('Chọn một file Revit trước khi tiếp tục');
      return;
    }
    const completeValues = { ...DEFAULT_FORM_VALUES, ...values, modelFile: file };
    if (!preparedModel) {
      handlePrepare();
    } else if (!designPreview) {
      onPreview(completeValues);
    } else {
      onSubmit(completeValues);
    }
  };

  return (
    <aside className="design-panel">
      <Form
        form={form}
        layout="vertical"
        initialValues={DEFAULT_FORM_VALUES}
        onFinish={handleFinish}
        onValuesChange={() => { if (designPreview) onIntentChange(); }}
        requiredMark={false}
        className="design-form"
      >
        <Steps
          size="small"
          current={currentStep}
          items={[{ title: 'Model' }, { title: 'Thiết kế' }, { title: 'Xác nhận' }]}
          className="design-steps"
        />
        <Flex vertical gap={16}>
          <Card size="small" title={<SectionTitle icon={<BuildOutlined />} title="01 · Nguồn mô hình" />}>
            <Form.Item label="Mô hình LOD 100 (.rvt)" validateStatus={modelError ? 'error' : undefined} help={modelError} required>
              <Upload.Dragger
                accept=".rvt"
                beforeUpload={(file) => {
                  if (!file.name.toLowerCase().endsWith('.rvt')) {
                    setModelError('Chỉ hỗ trợ định dạng .rvt');
                    return Upload.LIST_IGNORE;
                  }
                  if (file.size > MAX_RVT_FILE_BYTES) {
                    setModelError('Dung lượng file không được vượt quá 2 GiB');
                    return Upload.LIST_IGNORE;
                  }
                  setModelError(undefined);
                  onModelChange();
                  return false;
                }}
                fileList={modelFiles}
                maxCount={1}
                multiple={false}
                onChange={({ fileList }) => {
                  setModelFiles(fileList.slice(-1));
                  onModelChange();
                }}
              >
                <Flex vertical align="center" gap={2}>
                  <CloudUploadOutlined className="upload-icon" />
                  <Typography.Text>Thả file RVT hoặc bấm để chọn</Typography.Text>
                  <Typography.Text type="secondary">Hệ thống sẽ đọc cổng, hàng rào, đường và các khối chức năng.</Typography.Text>
                </Flex>
              </Upload.Dragger>
            </Form.Item>
            {!preparedModel && (
              <Button block onClick={handlePrepare} loading={preparingModel} disabled={!modelFiles.length}>
                Phân tích cấu kiện có thể thiết kế
              </Button>
            )}
            {preparedModel && (
              <Flex vertical gap={8}>
                <Typography.Text type="success"><CheckCircleFilled /> Đã phân tích {preparedModel.fileName}</Typography.Text>
                <Flex wrap gap={6}>
                  {preparedModel.capabilities.components.map((item) => (
                    <Tag key={item.key} color={item.supported ? 'blue' : 'default'}>
                      {item.label} · {item.supported ? item.evidence_count : 'không có'}
                    </Tag>
                  ))}
                </Flex>
              </Flex>
            )}
            <Form.Item label="Mã dự án" name="projectId" rules={[
              { required: true, message: 'Nhập mã dự án' },
              { pattern: /^[A-Za-z0-9][A-Za-z0-9._-]*$/, message: 'Chỉ dùng chữ, số, dấu chấm, gạch ngang hoặc gạch dưới' },
            ]} className="last-form-item">
              <Input placeholder="Ví dụ: factory-campus-01" />
            </Form.Item>
          </Card>

          <fieldset
            disabled={!preparedModel}
            className={`semantic-controls${preparedModel ? '' : ' is-disabled'}`}
          >
            <Card size="small" title={<SectionTitle icon={<SettingOutlined />} title="02 · Hệ kiến trúc công nghiệp" />}>
              <Form.Item label="Gói thiết kế" name="designPackage" tooltip="Một hệ ngôn ngữ đồng nhất cho toàn bộ 6 góc nhìn.">
                <Select options={designOptions.design_packages} optionRender={(option) => (
                  <Flex vertical><span>{option.label}</span><Typography.Text type="secondary">{option.data.description}</Typography.Text></Flex>
                )} />
              </Form.Item>
              <Form.Item label="Hệ bao che" name="envelopeKit"><Select options={designOptions.envelope_kits} /></Form.Item>
              <Form.Item label="Nhịp mặt đứng" name="facadeRhythmKit"><Segmented block options={designOptions.facade_rhythm_kits} /></Form.Item>
              <Form.Item label="Lối vào văn phòng" name="officeEntranceKit"><Select options={constrainedOptions(designOptions.office_entrance_kits)} /></Form.Item>
              <Form.Item label="Khu xuất nhập hàng" name="logisticsKit"><Select options={constrainedOptions(designOptions.logistics_kits)} /></Form.Item>
              <Form.Item label="Hàng rào" name="boundaryKit"><Select options={constrainedOptions(designOptions.boundary_kits)} /></Form.Item>
              <Form.Item label="Cổng" name="gateKit"><Select options={constrainedOptions(designOptions.gate_kits)} /></Form.Item>
              <Form.Item label="Diện tích màu nhận diện tối đa" name="accentCoveragePercent" className="last-form-item">
                <Segmented block options={[{ label: '3% · Rất nhẹ', value: 3 }, { label: '5% · Cân bằng', value: 5 }, { label: '8% · Rõ nét', value: 8 }]} />
              </Form.Item>
            </Card>

            <Card size="small" title={<SectionTitle icon={<BgColorsOutlined />} title="03 · Vật liệu và màu" />}>
              <Typography.Paragraph type="secondary" className="card-intro">
                Màu được khóa theo vai trò: mái, thân xưởng, chi tiết, kính, nhận diện, hàng rào và paving.
              </Typography.Paragraph>
              <Form.Item name="palette" className="last-form-item"><PaletteEditor /></Form.Item>
            </Card>

            <Collapse items={[{
              key: 'presentation', forceRender: true,
              label: <SectionTitle icon={<EyeOutlined />} title="04 · Bối cảnh và chất lượng" />,
              children: <>
                <Form.Item label="Cảnh quan" name="landscapePreset"><Select options={constrainedOptions(designOptions.landscapes)} /></Form.Item>
                <Form.Item label="Hoạt động vận hành" name="operatingScene"><Select options={constrainedOptions(designOptions.operating_scenes)} /></Form.Item>
                <Form.Item label="Thời điểm" name="time"><Input type="time" /></Form.Item>
                <Form.Item label="Mục tiêu hình ảnh" name="realismPreset"><Select options={designOptions.realism_presets} /></Form.Item>
                <Form.Item label="Chất lượng lượt sinh" name="deliveryQuality" className="last-form-item"><Segmented block options={designOptions.delivery_qualities} /></Form.Item>
              </>,
            }]} />

            <Card size="small" title={<SectionTitle icon={<SettingOutlined />} title="Yêu cầu bổ sung" />}>
              <Form.Item name="creativePrompt" className="last-form-item">
                <Input.TextArea rows={3} maxLength={1000} showCount placeholder="Chỉ mô tả ưu tiên về vật liệu, ánh sáng hoặc cảm giác không gian; không yêu cầu đổi hình học." />
              </Form.Item>
            </Card>
          </fieldset>

          {designPreview && (
            <Alert
              type={designPreview.warnings.length ? 'warning' : 'success'}
              showIcon
              message="Phương án đã được kiểm tra"
              description={designPreview.warnings.length
                ? designPreview.warnings.map((item) => item.message).join(' ')
                : 'Các lựa chọn phù hợp với semantic evidence của model. Có thể tạo Design Master.'}
            />
          )}
        </Flex>

        <Flex vertical gap={8} className="form-actions">
          <Button
            type="primary"
            htmlType="submit"
            loading={preparingModel || previewingDesign || submitting}
            icon={<ArrowRightOutlined />}
            block
          >
            {!preparedModel ? 'Phân tích model' : !designPreview ? 'Kiểm tra phương án' : 'Tạo Design Master'}
          </Button>
          <Typography.Text type="secondary" className="action-caption">
            {!preparedModel
              ? 'Chưa gọi AI sinh ảnh.'
              : !designPreview
                ? 'Preview và kiểm tra rule trước khi phát sinh chi phí.'
                : 'Chỉ sinh một góc master để duyệt trước 5 góc còn lại.'}
          </Typography.Text>
        </Flex>
      </Form>
    </aside>
  );
}
