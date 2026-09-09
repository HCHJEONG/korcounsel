import { test, expect } from '@playwright/test'

test('real API connection and narrow layout', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '개발 기반 준비' })).toBeVisible()
  await page.getByRole('button', { name: '연결 확인' }).click()
  await expect(page.getByRole('status')).toHaveText('API에 정상적으로 연결되었습니다.')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.screenshot({ path: `test-results/scaffold-${test.info().project.name}.png`, fullPage: true })
})

test('failed connection can be retried', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ status: 503, body: '{}' }))
  await page.goto('/')
  await page.getByRole('button', { name: '연결 확인' }).click()
  await expect(page.getByRole('status')).toContainText('연결할 수 없습니다')
  await page.unroute('**/api/health')
  await page.getByRole('button', { name: '연결 확인' }).click()
  await expect(page.getByRole('status')).toContainText('정상적으로 연결')
})

test('invalid successful payload is not treated as healthy', async ({ page }) => {
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok', service: 'other' } }))
  await page.goto('/')
  await page.getByRole('button', { name: '연결 확인' }).click()
  await expect(page.getByRole('status')).toContainText('연결할 수 없습니다')
})
