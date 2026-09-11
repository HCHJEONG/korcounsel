import { test, expect } from '@playwright/test'

test('login landing hides corpus and permits exactly configured administrator and editor', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'KorCounsel 로그인' })).toBeVisible()
  await expect(page.getByPlaceholder('아이디를 입력하세요')).toBeVisible()
  await expect(page.getByPlaceholder('비밀번호를 입력하세요')).toHaveAttribute('type', 'password')
  await expect(page.getByRole('heading', { name: '판례 검색', exact: true })).toHaveCount(0)
  await page.screenshot({ path: `test-results/login-landing-${test.info().project.name}.png`, fullPage: true })
  const fill = async (id: string, password: string) => {
    await page.getByLabel('아이디', { exact: true }).fill(id)
    await page.getByLabel('비밀번호', { exact: true }).fill(password)
    await page.getByRole('button', { name: '로그인', exact: true }).click()
  }
  await fill('unlisted-browser-test', process.env.KLEGAL_E2E_PASSWORD!)
  await expect(page.getByRole('status')).toContainText('아이디 또는 비밀번호')
  await fill('reader-browser-test', process.env.KLEGAL_E2E_PASSWORD!)
  await expect(page.locator('.account-menu')).toContainText('관리자')
  await page.getByRole('button', { name: '로그아웃' }).click()
  await fill('editor-browser-test', process.env.KLEGAL_E2E_EDITOR_PASSWORD!)
  await expect(page.locator('.account-menu')).toContainText('편집자')
  await page.getByRole('button', { name: '로그아웃' }).click()
  expect((await page.request.get('/api/cases/search?q=대법원')).status()).toBe(401)
})

