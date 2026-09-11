import { expect, test, type Page } from '@playwright/test';

const supportedComponents = [
  'envelope', 'office_entrance', 'logistics', 'boundary', 'gate',
  'landscape', 'circulation', 'roof_finish',
].map((key) => ({
  key,
  label: key,
  supported: true,
  evidence_count: 1,
  evidence_ids: [`${key}-01`],
  reason: 'Có semantic evidence.',
}));

async function mockDesignValidation(page: Page, modelRevision: string) {
  await page.route('**/v1/models/*/design-capabilities', (route) => route.fulfill({
    json: {
      schema_version: '1.0.0',
      model_revision: modelRevision,
      components: supportedComponents,
      warnings: [],
    },
  }));
  await page.route('**/v1/models/*/design-preview', async (route) => {
    const request = await route.request().postDataJSON() as { intent: Record<string, unknown> };
    return route.fulfill({
      json: {
        model_revision: modelRevision,
        preview_token: 'a'.repeat(64),
        normalized_intent: request.intent,
        capabilities: {
          schema_version: '1.0.0', model_revision: modelRevision,
          components: supportedComponents, warnings: [],
        },
        warnings: [],
      },
    });
  });
}

async function advanceToDesignMaster(page: Page, projectId: string) {
  await page.locator('input[type="file"]').setInputFiles({
    name: 'factory.rvt', mimeType: 'application/octet-stream', buffer: Buffer.from('rvt-content'),
  });
  await page.getByRole('button', { name: 'Phân tích cấu kiện có thể thiết kế' }).click();
  await expect(page.getByText(/Đã phân tích factory.rvt/)).toBeVisible();
  await page.getByLabel('Mã dự án').fill(projectId);
  await page.getByRole('button', { name: 'Kiểm tra phương án' }).click();
  await expect(page.getByText('Phương án đã được kiểm tra')).toBeVisible();
  await page.getByRole('button', { name: 'Tạo Design Master' }).click();
}

test('configures a design and follows the generation output', async ({ page }) => {
  let submittedIntent: Record<string, unknown> | undefined;
  let videoRequested = false;

  await page.route('**/v1/design-options', (route) => route.abort());

  await page.route('**/v1/models', async (route) => {
    expect(route.request().method()).toBe('POST');
    expect(route.request().headers()['x-filename']).toBe('factory.rvt');
    await route.fulfill({
      status: 201,
      json: {
        model_revision: 'model-revision-e2e',
        file_name: 'factory.rvt',
        size_bytes: 11,
        ready: true,
      },
    });
  });
  await mockDesignValidation(page, 'model-revision-e2e');
  await page.route('**/v1/projects/*/design-revisions', async (route) => {
    submittedIntent = (await route.request().postDataJSON()) as Record<string, unknown>;
    await route.fulfill({ status: 201, json: { design_revision: 'R01-e2e' } });
  });
  await page.route('**/v1/design-revisions/*/view-sets', (route) =>
    route.fulfill({
      status: 202,
      json: {
        job_id: 'job-e2e',
        trace_id: 'trace-e2e-123456789',
        view_set_id: 'viewset-e2e',
        design_revision: 'R01-e2e',
        state: 'rendering_passes',
      },
    }),
  );
  await page.route('**/v1/view-sets/viewset-e2e/outputs', (route) =>
    route.fulfill({
      json: {
        outputs: [
          {
            id: 'image-view-01',
            kind: 'image',
            title: 'VIEW-01',
            view_id: 'view-01',
            url: 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="%23dbeafe"/></svg>',
          },
        ],
      },
    }),
  );
  await page.route('**/v1/view-sets/viewset-e2e', (route) =>
    route.fulfill({
      json: {
        job_id: 'job-e2e',
        trace_id: 'trace-e2e-123456789',
        view_set_id: 'viewset-e2e',
        design_revision: 'R01-e2e',
        state: 'completed',
        certification_state: 'marketing_generative_review',
      },
    }),
  );
  await page.route('**/v1/view-sets/viewset-e2e/video-jobs', (route) => {
    videoRequested = true;
    return route.fulfill({
      status: 202,
      json: {
        video_job_id: 'video-job-e2e',
        view_set_id: 'viewset-e2e',
        state: 'queued',
        created: true,
        estimated_cost_usd: 1.2,
        output_url: null,
      },
    });
  });

  await page.goto('/');

  const logo = page.getByRole('img', { name: 'TD Group' });
  await expect(logo).toBeVisible();
  await expect
    .poll(() => logo.evaluate((image: HTMLImageElement) => image.naturalWidth))
    .toBeGreaterThan(0);
  await expect(page.getByText('01 · Nguồn mô hình')).toBeVisible();
  await expect(page.getByText('V365 Render Studio')).toBeVisible();
  await expect(page.getByLabel('Model revision')).toHaveCount(0);
  await expect(page.getByText('Độ dốc mái')).toHaveCount(0);

  await page.locator('input[type="file"]').setInputFiles({ name: 'factory.rvt', mimeType: 'application/octet-stream', buffer: Buffer.from('rvt-content') });
  await page.getByRole('button', { name: 'Phân tích cấu kiện có thể thiết kế' }).click();
  await page.getByLabel('Mã dự án').fill('factory-e2e');
  await page
    .getByPlaceholder(/Chỉ mô tả ưu tiên/)
    .fill('Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.');
  await page.getByRole('button', { name: 'Kiểm tra phương án' }).click();
  await page.getByRole('button', { name: 'Tạo Design Master' }).click();

  await expect(page.getByText('Đang dựng geometry passes').first()).toBeVisible();
  await expect(page.getByText('Đã hoàn tất').first()).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText('VIEW-01', { exact: true }).last()).toBeVisible();
  expect(videoRequested).toBe(false);

  await page.getByRole('button', { name: 'Tạo video trình diễn' }).click();
  await page.getByRole('button', { name: 'Tạo video', exact: true }).click();
  await expect(page.getByText('Đang chờ tạo video')).toBeVisible();
  expect(videoRequested).toBe(true);

  expect(submittedIntent).toMatchObject({
    model_revision: 'model-revision-e2e',
    intent: {
      design_package: 'premium_practical',
      facade_rhythm_kit: 'mixed_restrained',
      free_text: 'Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.',
      time: '09:30',
    },
    preview_token: 'a'.repeat(64),
  });
});

test('shows FastAPI validation failures as a notification', async ({ page }) => {
  await page.route('**/v1/design-options', (route) => route.abort());
  await page.route('**/v1/models', (route) =>
    route.fulfill({
      status: 201,
      json: {
        model_revision: 'model-revision-e2e',
        file_name: 'factory.rvt',
        size_bytes: 11,
        ready: true,
      },
    }),
  );
  await mockDesignValidation(page, 'model-revision-e2e');
  await page.route('**/v1/projects/*/design-revisions', (route) =>
    route.fulfill({
      status: 422,
      json: {
        detail: [
          {
            loc: ['body', 'intent', 'time'],
            msg: 'Field required',
            type: 'missing',
          },
        ],
      },
    }),
  );

  await page.goto('/');
  await advanceToDesignMaster(page, 'factory-e2e');

  const notice = page.locator('.ant-notification-notice-error');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText('Không thể tạo phương án diễn họa');
  await expect(notice).toContainText('intent.time: Field required');
  await expect(notice).not.toContainText('[object Object]');
});

test('shows generated images at human review and resumes board composition', async ({ page }) => {
  let approved = false;
  const image =
    'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="%23dbeafe"/></svg>';
  const images = Array.from({ length: 6 }, (_, index) => ({
    id: `image-view-0${index + 1}`,
    kind: 'image',
    title: `VIEW-0${index + 1}`,
    view_id: `view-0${index + 1}`,
    url: image,
  }));
  await page.route('**/v1/design-options', (route) => route.abort());
  await page.route('**/v1/models', (route) =>
    route.fulfill({
      status: 201,
      json: { model_revision: 'model-review', file_name: 'factory.rvt', size_bytes: 11, ready: true },
    }),
  );
  await mockDesignValidation(page, 'model-review');
  await page.route('**/v1/projects/*/design-revisions', (route) =>
    route.fulfill({ status: 201, json: { design_revision: 'R01-review' } }),
  );
  await page.route('**/v1/design-revisions/*/view-sets', (route) =>
    route.fulfill({
      status: 202,
      json: {
        job_id: 'job-review',
        trace_id: 'trace-review-123456',
        view_set_id: 'viewset-review',
        design_revision: 'R01-review',
        state: 'human_review',
      },
    }),
  );
  await page.route('**/v1/view-sets/viewset-review/outputs', (route) =>
    route.fulfill({
      json: {
        outputs: approved
          ? [...images, { id: 'board', kind: 'board', title: 'Bộ 6 góc nhìn', url: image }]
          : images,
      },
    }),
  );
  await page.route('**/v1/view-sets/viewset-review/approve', (route) => {
    approved = true;
    return route.fulfill({
      status: 202,
      json: {
        job_id: 'job-review',
        trace_id: 'trace-review-123456',
        view_set_id: 'viewset-review',
        design_revision: 'R01-review',
        state: 'composing_board',
      },
    });
  });
  await page.route('**/v1/view-sets/viewset-review', (route) =>
    route.fulfill({
      json: {
        job_id: 'job-review',
        trace_id: 'trace-review-123456',
        view_set_id: 'viewset-review',
        design_revision: 'R01-review',
        state: approved ? 'completed' : 'human_review',
      },
    }),
  );

  await page.goto('/');
  await advanceToDesignMaster(page, 'factory-review');

  await expect(page.getByText('Bộ 6 ảnh đã được tạo và đang chờ duyệt')).toBeVisible();
  await expect(page.locator('.artifact-card')).toHaveCount(6);
  await page.getByRole('button', { name: 'Duyệt và hoàn thiện board' }).click();
  await expect(page.getByText('Đã hoàn tất').first()).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText('Bộ 6 góc nhìn')).toBeVisible();
});

test('stops after one Design Master and only generates remaining views after approval', async ({ page }) => {
  let masterApproved = false;
  const image =
    'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="%23dbeafe"/></svg>';
  const master = {
    id: 'image-view-04',
    kind: 'image',
    title: 'VIEW-04',
    view_id: 'view-04',
    url: image,
  };
  const remaining = [1, 2, 3, 5, 6].map((index) => ({
    id: `image-view-0${index}`,
    kind: 'image',
    title: `VIEW-0${index}`,
    view_id: `view-0${index}`,
    url: image,
  }));

  await page.route('**/v1/design-options', (route) => route.abort());
  await page.route('**/v1/models', (route) =>
    route.fulfill({
      status: 201,
      json: { model_revision: 'model-master', file_name: 'factory.rvt', size_bytes: 11, ready: true },
    }),
  );
  await mockDesignValidation(page, 'model-master');
  await page.route('**/v1/projects/*/design-revisions', (route) =>
    route.fulfill({ status: 201, json: { design_revision: 'R01-master' } }),
  );
  await page.route('**/v1/design-revisions/*/view-sets', (route) =>
    route.fulfill({
      status: 202,
      json: {
        job_id: 'job-master',
        trace_id: 'trace-master-123456',
        view_set_id: 'viewset-master',
        design_revision: 'R01-master',
        state: 'design_master_review',
      },
    }),
  );
  await page.route('**/v1/view-sets/viewset-master/outputs', (route) =>
    route.fulfill({ json: { outputs: masterApproved ? [master, ...remaining] : [master] } }),
  );
  await page.route('**/v1/view-sets/viewset-master/approve', (route) => {
    masterApproved = true;
    return route.fulfill({
      status: 202,
      json: {
        job_id: 'job-master',
        trace_id: 'trace-master-123456',
        view_set_id: 'viewset-master',
        design_revision: 'R01-master',
        state: 'generating_viewset',
      },
    });
  });
  await page.route('**/v1/view-sets/viewset-master', (route) =>
    route.fulfill({
      json: {
        job_id: 'job-master',
        trace_id: 'trace-master-123456',
        view_set_id: 'viewset-master',
        design_revision: 'R01-master',
        state: masterApproved ? 'human_review' : 'design_master_review',
      },
    }),
  );

  await page.goto('/');
  await advanceToDesignMaster(page, 'factory-master');

  await expect(page.getByText('Duyệt Design Master trước khi sinh toàn bộ view set')).toBeVisible();
  await expect(page.locator('.artifact-card')).toHaveCount(1);
  await page.getByRole('button', { name: 'Duyệt và tạo 5 góc còn lại' }).click();
  await expect(page.getByText('Bộ 6 ảnh đã được tạo và đang chờ duyệt')).toBeVisible({ timeout: 8_000 });
  await expect(page.locator('.artifact-card')).toHaveCount(6);
});

test('keeps material colors as valid hex values when using the color picker', async ({ page }) => {
  await page.route('**/v1/design-options', (route) => route.abort());
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 201,
    json: { model_revision: 'model-color', file_name: 'factory.rvt', size_bytes: 11, ready: true },
  }));
  await mockDesignValidation(page, 'model-color');
  await page.goto('/');
  await page.locator('input[type="file"]').setInputFiles({
    name: 'factory.rvt', mimeType: 'application/octet-stream', buffer: Buffer.from('rvt-content'),
  });
  await page.getByRole('button', { name: 'Phân tích cấu kiện có thể thiết kế' }).click();

  const input = page.getByRole('textbox', { name: 'Thân nhà', exact: true });
  const picker = page.getByLabel('Chọn thân nhà', { exact: true });
  await input.fill('#D45500');
  await input.blur();
  await expect(input).toHaveValue('#D45500');

  await picker.click();
  const saturation = page.locator('.ant-color-picker-saturation');
  const box = await saturation.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    await page.mouse.click(box.x + box.width * 0.8, box.y + box.height * 0.25);
  }

  await expect(input).toHaveValue(/^#[0-9A-F]{6}$/);
  await expect(input).not.toHaveValue('#000000');
  await expect(picker.locator('.ant-color-picker-color-block-inner')).not.toHaveAttribute(
    'style',
    /rgb\(0, 0, 0\)/,
  );
});

test('warns about an unsuitable material system and can rebalance it', async ({ page }) => {
  await page.route('**/v1/design-options', (route) => route.abort());
  await page.route('**/v1/models', (route) => route.fulfill({
    status: 201,
    json: { model_revision: 'model-palette', file_name: 'factory.rvt', size_bytes: 11, ready: true },
  }));
  await mockDesignValidation(page, 'model-palette');
  await page.goto('/');
  await page.locator('input[type="file"]').setInputFiles({
    name: 'factory.rvt', mimeType: 'application/octet-stream', buffer: Buffer.from('rvt-content'),
  });
  await page.getByRole('button', { name: 'Phân tích cấu kiện có thể thiết kế' }).click();

  await page.getByRole('textbox', { name: 'Mái', exact: true }).fill('#202020');
  await page.getByRole('textbox', { name: 'Mái', exact: true }).blur();
  await page.getByRole('textbox', { name: 'Thân nhà', exact: true }).fill('#FF0000');
  await page.getByRole('textbox', { name: 'Thân nhà', exact: true }).blur();
  await page.getByRole('textbox', { name: 'Kết cấu', exact: true }).fill('#0000FF');
  await page.getByRole('textbox', { name: 'Kết cấu', exact: true }).blur();

  await expect(page.getByText('Phối màu cần cân nhắc')).toBeVisible();
  await page.getByRole('button', { name: 'Tự cân bằng' }).click();
  await expect(page.getByRole('textbox', { name: 'Mái', exact: true })).not.toHaveValue('#202020');
  await expect(page.getByRole('textbox', { name: 'Kết cấu', exact: true })).not.toHaveValue('#0000FF');
});
