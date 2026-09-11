import { expect, test } from '@playwright/test';

test('configures a design and follows the generation output', async ({ page }) => {
  let submittedIntent: Record<string, unknown> | undefined;
  let videoRequested = false;

  await page.route('**/v1/design-options', (route) =>
    route.fulfill({
      json: {
        schema_version: '1.0.0',
        catalog_version: 'industrial-intent-v1',
        styles: [
          { value: 'contemporary_industrial', label: 'Công nghiệp đương đại', description: 'Mặc định' },
        ],
        decor_levels: [
          { value: 'minimal', label: 'Tối giản', description: 'Ít' },
          { value: 'subtle', label: 'Nhẹ', description: 'Nhẹ' },
          { value: 'balanced', label: 'Cân bằng', description: 'Vừa' },
          { value: 'expressive', label: 'Nổi bật', description: 'Nhiều' },
        ],
        landscapes: [
          { value: 'tropical_restrained', label: 'Nhiệt đới tiết chế', description: 'Khí hậu' },
        ],
        creative_budgets: [
          { value: 'balanced', label: 'Cân bằng', description: 'Vừa' },
        ],
        loading_dock_policies: [
          { value: 'suggest_if_missing', label: 'Đề xuất khi thiếu', description: 'Có kiểm soát' },
        ],
        context_presentations: [
          { value: 'authored_only', label: 'Chỉ theo model', description: 'Không phát sinh' },
        ],
        realism_presets: [
          { value: 'documentary_architectural_photo', label: 'Ảnh kiến trúc chân thật', description: 'Ảnh chụp' },
        ],
      },
    }),
  );

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
  await expect(page.getByText('Thông tin dự án')).toBeVisible();
  await expect(page.getByText('V365 Render Studio')).toBeVisible();
  await expect(page.getByLabel('Model revision')).toHaveCount(0);
  await expect(page.getByText('Độ dốc mái')).toHaveCount(0);

  await page.locator('input[type="file"]').setInputFiles({
    name: 'factory.rvt',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('rvt-content'),
  });
  await page.getByLabel('Mã dự án').fill('factory-e2e');
  await page.getByText('Nổi bật', { exact: true }).click();
  await page
    .getByPlaceholder(/Mô tả ngắn/)
    .fill('Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.');
  await page.getByRole('button', { name: /Tạo phương án diễn họa/ }).click();

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
      style_preset: 'contemporary_industrial',
      decor_level: 'expressive',
      free_text: 'Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.',
      time: '09:30',
      context_presentation: 'authored_only',
    },
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
  await page.locator('input[type="file"]').setInputFiles({
    name: 'factory.rvt',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('rvt-content'),
  });
  await page.getByLabel('Mã dự án').fill('factory-e2e');
  await page.getByRole('button', { name: /Tạo phương án diễn họa/ }).click();

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
  await page.locator('input[type="file"]').setInputFiles({
    name: 'factory.rvt',
    mimeType: 'application/octet-stream',
    buffer: Buffer.from('rvt-content'),
  });
  await page.getByLabel('Mã dự án').fill('factory-review');
  await page.getByRole('button', { name: /Tạo phương án diễn họa/ }).click();

  await expect(page.getByText('Bộ 6 ảnh đã được tạo và đang chờ duyệt')).toBeVisible();
  await expect(page.locator('.artifact-card')).toHaveCount(6);
  await page.getByRole('button', { name: 'Duyệt và hoàn thiện board' }).click();
  await expect(page.getByText('Đã hoàn tất').first()).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText('Bộ 6 góc nhìn')).toBeVisible();
});
