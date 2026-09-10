import { expect, test } from '@playwright/test';

test('configures a design and follows the generation output', async ({ page }) => {
  let submittedBrief: Record<string, unknown> | undefined;
  let videoRequested = false;

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
    submittedBrief = (await route.request().postDataJSON()) as Record<string, unknown>;
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

  expect(submittedBrief).toMatchObject({
    model_revision: 'model-revision-e2e',
    brief: {
      project_id: 'factory-e2e',
      design_preferences: {
        decor_level: 'expressive',
        creative_prompt: 'Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.',
      },
      environment: {
        time: '09:30',
      },
      roof_slope_deg: 7,
      add_office_entrances: true,
    },
  });
});

test('shows FastAPI validation failures as a notification', async ({ page }) => {
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
            loc: ['body', 'brief', 'environment', 'time'],
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
  await expect(notice).toContainText('brief.environment.time: Field required');
  await expect(notice).not.toContainText('[object Object]');
});
