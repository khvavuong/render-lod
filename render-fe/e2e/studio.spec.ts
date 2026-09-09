import { expect, test } from '@playwright/test';

const transparentPixel = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M/wHwAEAQH/6KYXjgAAAABJRU5ErkJggg==',
  'base64',
);

test('configures a design and follows the generation output', async ({ page }) => {
  let submittedBrief: Record<string, unknown> | undefined;

  await page.route('**/v1/brand/logo', (route) =>
    route.fulfill({ status: 200, contentType: 'image/png', body: transparentPixel }),
  );
  await page.route('**/v1/models/latest', (route) =>
    route.fulfill({ json: { model_revision: 'model-revision-e2e' } }),
  );
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
      },
    }),
  );

  await page.goto('/');

  await expect(page.getByRole('heading', { name: 'Thiết lập phương án' })).toBeVisible();
  await expect(page.getByText('Không gian tạo sinh')).toBeVisible();
  await expect(page.getByLabel('Model revision')).toHaveCount(0);
  await expect(page.getByText('Độ dốc mái')).toHaveCount(0);

  await page.getByLabel('Mã dự án').fill('factory-e2e');
  await page.getByText('Nổi bật', { exact: true }).click();
  await page
    .getByPlaceholder(/sảnh đón chuyên nghiệp/)
    .fill('Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.');
  await page.getByRole('button', { name: /Tạo phương án diễn họa/ }).click();

  await expect(page.getByText('Đang dựng geometry passes').first()).toBeVisible();
  await expect(page.getByText('Đã hoàn tất').first()).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText('VIEW-01', { exact: true }).last()).toBeVisible();

  expect(submittedBrief).toMatchObject({
    model_revision: 'model-revision-e2e',
    brief: {
      project_id: 'factory-e2e',
      design_preferences: {
        decor_level: 'expressive',
        creative_prompt: 'Ưu tiên mặt đứng tinh tế và ánh sáng tự nhiên.',
      },
      roof_slope_deg: 7,
      add_office_entrances: true,
    },
  });
});
