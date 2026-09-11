import { test, expect } from '@playwright/test'

async function login(page: import('@playwright/test').Page) {
  await page.goto('/')
  await page.getByLabel('아이디', { exact: true }).fill('reader-browser-test')
  await page.getByLabel('비밀번호', { exact: true }).fill(process.env.KLEGAL_E2E_PASSWORD!)
  await page.getByRole('button', { name: '로그인', exact: true }).click()
  await expect(page.getByRole('heading', { name: '판례 검색과 본문 열람' })).toBeVisible()
}

test('real saved images, repeated positions, failure placeholders and logout', async ({ page }) => {
  const external: string[] = []
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
      external.push(url.href)
      await route.abort()
    } else await route.continue()
  })
  await login(page)
  await page.getByRole('button', { name: '대법원 2008. 2. 28. 선고 2006후4086 판결', exact: true }).click()
  const frame = page.frameLocator('iframe[title="판례 본문"]')
  await expect(frame.locator('img')).toHaveCount(2)
  await expect.poll(() => frame.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).complete && (img as HTMLImageElement).naturalWidth > 0))).toBe(true)
  const paths = await frame.locator('img').evaluateAll(images => images.map(img => (img as HTMLImageElement).src))
  expect(paths[0]).not.toEqual(paths[1])
  expect(paths.every(path => path.includes('/api/reader/'))).toBe(true)
  await page.screenshot({ path: `test-results/reader-real-${test.info().project.name}.png`, fullPage: true })
  await page.getByRole('button', { name: '대법원 2010. 5. 13. 선고 2009다47340 판결', exact: true }).click()
  await expect(frame.locator('img')).toHaveCount(4)
  await expect(frame.locator('.missing-image')).toHaveCount(2)
  await expect.poll(() => frame.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await page.getByRole('button', { name: '대법원 2006. 11. 23. 선고 2005후1356 판결', exact: true }).click()
  await expect(frame.locator('.missing-image')).toHaveCount(3)
  expect(external).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: '로그아웃', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'KorCounsel 로그인' })).toBeVisible()
  expect((await page.request.get(paths[0])).status()).toBe(401)
  await expect(page.locator('iframe')).toHaveCount(0)
})

test('Parquet search opens version-bound legacy body and session expiry clears it', async ({ page }) => {
  await login(page)
  await page.getByLabel('법원명 · 사건번호 · 본문 문자열').fill('대법원')
  await page.getByRole('button', { name: '검색', exact: true }).click()
  await expect(page.getByRole('button', { name: '본문 열기' }).first()).toBeVisible()
  await page.getByRole('button', { name: '본문 열기' }).first().click()
  await expect(page.frameLocator('iframe').locator('body')).toContainText('대법원')
  await page.reload()
  await expect(page.getByRole('heading', { name: '판례 검색과 본문 열람' })).toBeVisible()
  await expect(page.frameLocator('iframe').locator('body')).toContainText('대법원')
  await page.context().clearCookies()
  await page.getByRole('button', { name: '대법원 2008. 2. 28. 선고 2006후4086 판결', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'KorCounsel 로그인' })).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)
})



test('normal search shows preserved statutes and repeated local images with pinned revision', async ({ page }) => {
  test.setTimeout(180000)
  const external: string[] = []
  await page.route('**/*', async route => {
    if (!['127.0.0.1', 'localhost'].includes(new URL(route.request().url()).hostname)) {
      external.push(route.request().url()); await route.abort()
    } else await route.continue()
  })
  await login(page)
  await page.getByLabel('법원명 · 사건번호 · 본문 문자열').fill('2006후4086')
  await page.getByRole('button', { name: '검색', exact: true }).click()
  const row = page.locator('tbody tr').filter({ hasText: '대법원 2008. 2. 28. 선고 2006후4086 판결' })
  await expect(row).toBeVisible({ timeout: 45000 })
  await row.getByRole('button', { name: '본문 열기' }).click()
  const frame = page.frameLocator('iframe[title="판례 본문"]')
  await expect(frame.locator('img')).toHaveCount(2)
  await expect.poll(() => frame.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await frame.locator('img').first().scrollIntoViewIfNeeded()
  await page.screenshot({ path: `test-results/legacy-image-${test.info().project.name}.png`, fullPage: true })
  await expect(frame.locator('.statute-item')).toHaveCount(4)
  await expect(frame.locator('.statute-item table')).toHaveCount(2)
  await expect(frame.locator('.statute-item').first()).toContainText('상표법')
  await expect(frame.locator('.statute-item').first()).toContainText('적용 버전 미확인')
  await frame.locator('.statute-link').first().click()
  await expect(frame.locator('#statute-0')).toBeVisible()
  await page.screenshot({ path: `test-results/legacy-statute-${test.info().project.name}.png`, fullPage: true })
  await frame.locator('#statute-0').getByRole('link', { name: '원래 인용 위치로 돌아가기' }).click()
  await expect(frame.locator('#citation-0')).toBeVisible()
  expect(new URL(page.url()).searchParams.get('row')).toBe('8467')
  const revision = new URL(page.url()).searchParams.get('reader_revision')
  expect(revision).toMatch(/^[a-f0-9]{64}$/)
  await page.screenshot({ path: `test-results/legacy-enriched-${test.info().project.name}.png`, fullPage: true })
  await page.reload()
  await expect(frame.locator('img')).toHaveCount(2)
  expect(new URL(page.url()).searchParams.get('reader_revision')).toBe(revision)
  expect(external).toEqual([])
})

for (const sample of [
  { query: '2002고26', title: '제26사단보통군사법원 2002. 10. 24. 선고 2002고26 판결', tables: 12, images: 0, failure: false },
  { query: '2009도6256', title: '대법원 2011. 3. 10. 선고 2009도6256 판결', tables: 3, images: 0, failure: true },
  { query: '2010후3226', title: '대법원 2011. 3. 10. 선고 2010후3226 판결', tables: 7, images: 1, failure: false },
]) {
  test(`normal search enrichment ${sample.query}`, async ({ page }) => {
    test.setTimeout(180000)
    await login(page)
    await page.getByLabel('법원명 · 사건번호 · 본문 문자열').fill(sample.query)
    await page.getByRole('button', { name: '검색', exact: true }).click()
    const row = page.locator('tbody tr').filter({ hasText: sample.title })
    await expect(row).toBeVisible({ timeout: 45000 })
    await row.getByRole('button', { name: '본문 열기' }).click()
    const frame = page.frameLocator('iframe[title="판례 본문"]')
    await expect(frame.locator('.statute-item table')).toHaveCount(sample.tables)
    await expect(frame.locator('img')).toHaveCount(sample.images)
    if (sample.images) await expect.poll(() => frame.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).naturalWidth > 0))).toBe(true)
    if (sample.failure) await expect(frame.locator('body')).toContainText('과거 보강 실패: jomun not registered at 법제처')
  })
}
