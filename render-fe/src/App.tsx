import { App as AntdApp, ConfigProvider, notification } from "antd";
import viVN from "antd/locale/vi_VN";
import { useEffect, useState, type CSSProperties } from "react";

import { DesignPanel } from "./components/DesignPanel";
import { GenerationWorkspace } from "./components/GenerationWorkspace";
import { FALLBACK_DESIGN_OPTIONS } from "./domain/design-brief";
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

function StudioShell({ gateway }: Required<AppProps>) {
  const [designOptions, setDesignOptions] = useState(FALLBACK_DESIGN_OPTIONS);
  const {
    job,
    videoJob,
    isSubmitting,
    isPreparingModel,
    isPreviewingDesign,
    preparedModel,
    designPreview,
    isSubmittingVideo,
    isSubmittingReview,
    error,
    errorTitle,
    submit,
    prepareModel,
    previewDesign,
    invalidateDesignPreview,
    resetPreparedModel,
    refresh,
    approve,
    retry,
    generateVideo,
  } = useStudioJob(gateway);
  const [notificationApi, notificationContext] = notification.useNotification();

  useEffect(() => {
    let active = true;
    if (!gateway.getDesignOptions) return undefined;
    void gateway
      .getDesignOptions()
      .then((options) => {
        if (active) setDesignOptions(options);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [gateway]);

  useEffect(() => {
    if (!error) {
      notificationApi.destroy("studio-error");
      return;
    }
    notificationApi.error({
      key: "studio-error",
      message: errorTitle,
      description: error,
      placement: "topRight",
      duration: 8,
    });
  }, [error, errorTitle, notificationApi]);

  useEffect(() => {
    if (!job?.intentWarnings?.length) return;
    notificationApi.warning({
      key: `intent-warning-${job.designRevision}`,
      message: "Lưu ý từ bộ kiểm soát thiết kế",
      description: job.intentWarnings.map((warning) => warning.message).join(" "),
      placement: "topRight",
      duration: 10,
    });
  }, [job, notificationApi]);

  return (
    <>
      {notificationContext}
      <div className="app-shell v365-render-studio" style={layoutStyle}>
        <header className="app-header">
          <div className="brand-lockup">
            <img src="/logo_vertical.png" alt="TD Group" />
          </div>
        </header>
        <div className="studio-layout">
          <DesignPanel
            submitting={isSubmitting}
            preparingModel={isPreparingModel}
            previewingDesign={isPreviewingDesign}
            preparedModel={preparedModel}
            designPreview={designPreview}
            designOptions={designOptions}
            onPrepareModel={(file) => void prepareModel(file)}
            onPreview={(values) => void previewDesign(values)}
            onIntentChange={invalidateDesignPreview}
            onModelChange={resetPreparedModel}
            onSubmit={(values) => void submit(values)}
          />
          <GenerationWorkspace
            job={job}
            videoJob={videoJob}
            submittingVideo={isSubmittingVideo}
            submittingReview={isSubmittingReview}
            onGenerateVideo={() => void generateVideo()}
            onRefresh={() => void refresh()}
            onApprove={() => void approve()}
            onRetry={() => void retry()}
          />
        </div>
      </div>
    </>
  );
}

export default function App({ gateway = studioApi }: AppProps) {
  return (
    <ConfigProvider locale={viVN} theme={appTheme}>
      <AntdApp>
        <StudioShell gateway={gateway} />
      </AntdApp>
    </ConfigProvider>
  );
}
