import { ConfigProvider } from "antd";
import viVN from "antd/locale/vi_VN";
import type { CSSProperties } from "react";

import { DesignPanel } from "./components/DesignPanel";
import { GenerationWorkspace } from "./components/GenerationWorkspace";
import { useStudioJob } from "./hooks/use-studio-job";
import { studioApi } from "./services/studio-api";
import { appTheme } from "./theme/theme";
import { CONTENT_PADDING, FORM_PANEL_WIDTH, HEADER_HEIGHT } from "./theme/tokens";
import type { StudioGateway } from "./types/studio";

interface AppProps {
  gateway?: StudioGateway;
}

const layoutStyle = {
  "--content-padding": `${CONTENT_PADDING}px`,
  "--form-panel-width": `${FORM_PANEL_WIDTH}px`,
  "--header-height": `${HEADER_HEIGHT}px`,
} as CSSProperties;

export default function App({ gateway = studioApi }: AppProps) {
  const { job, isSubmitting, error, submit, refresh } = useStudioJob(gateway);

  return (
    <ConfigProvider locale={viVN} theme={appTheme}>
      <div className="app-shell v365-render-studio" style={layoutStyle}>
        <header className="app-header">
          <div className="brand-lockup">
            <img src="/logo_vertical.png" alt="TD Group" />
          </div>
        </header>
        <div className="studio-layout">
          <DesignPanel
            submitting={isSubmitting}
            onSubmit={(values) => void submit(values)}
          />
          <GenerationWorkspace
            job={job}
            error={error}
            onRefresh={() => void refresh()}
          />
        </div>
      </div>
    </ConfigProvider>
  );
}
