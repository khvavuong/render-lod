import { SafetyCertificateOutlined } from '@ant-design/icons';
import { ConfigProvider, Tag, Typography } from 'antd';

import { DesignPanel } from './components/DesignPanel';
import { GenerationWorkspace } from './components/GenerationWorkspace';
import { useStudioJob } from './hooks/use-studio-job';
import { studioApi } from './services/studio-api';
import type { StudioGateway } from './types/studio';

interface AppProps {
  gateway?: StudioGateway;
}

const theme = {
  token: {
    colorPrimary: '#2563eb',
    colorInfo: '#2563eb',
    colorSuccess: '#16845b',
    colorText: '#172033',
    colorTextSecondary: '#667085',
    colorBgLayout: '#f5f7fb',
    borderRadius: 8,
    borderRadiusLG: 12,
    fontFamily: "Inter, 'SF Pro Display', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif",
  },
  components: {
    Button: { controlHeightLG: 46, fontWeight: 600 },
    Form: { itemMarginBottom: 18 },
    Input: { controlHeightLG: 42 },
    Select: { controlHeightLG: 42 },
  },
};

export default function App({ gateway = studioApi }: AppProps) {
  const { job, isSubmitting, error, submit, refresh } = useStudioJob(gateway);

  return (
    <ConfigProvider theme={theme}>
      <div className="app-shell">
        <header className="app-header">
          <div className="brand-lockup">
            <img src="/v1/brand/logo" alt="TD Group" />
            <span className="brand-divider" />
            <Typography.Text strong>Render Studio</Typography.Text>
          </div>
          <Tag icon={<SafetyCertificateOutlined />} variant="filled" className="geometry-badge">
            Geometry-first
          </Tag>
        </header>
        <div className="studio-layout">
          <DesignPanel submitting={isSubmitting} onSubmit={(values) => void submit(values)} />
          <GenerationWorkspace job={job} error={error} onRefresh={() => void refresh()} />
        </div>
      </div>
    </ConfigProvider>
  );
}
