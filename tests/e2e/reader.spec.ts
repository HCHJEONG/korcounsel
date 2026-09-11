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
  const samples = page.locator('.reader-samples')
  await expect(samples).not.toHaveAttribute('open', '')
  await samples.locator('summary').click()
  await expect(samples).toHaveAttribute('open', '')
  await samples.locator('.reader-list button').first().click()
  await expect(page.frameLocator('iframe[title="판례 본문"]').locator('body')).toBeVisible()
  await page.goto('/?document=93f8e6069bde1b0119cc59123c8839ff0e7e7d75da96a1ca7d388b928dd25d78')
  const frame = page.frameLocator('iframe[title="판례 본문"]')
  await expect(frame.locator('img')).toHaveCount(2)
  await expect.poll(() => frame.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).complete && (img as HTMLImageElement).naturalWidth > 0))).toBe(true)
  const paths = await frame.locator('img').evaluateAll(images => images.map(img => (img as HTMLImageElement).src))
  expect(paths[0]).not.toEqual(paths[1])
  expect(paths.every(path => path.includes('/api/reader/'))).toBe(true)
  await page.screenshot({ path: `test-results/reader-real-${test.info().project.name}.png`, fullPage: true })
  await page.goto('/?document=57b10a6d5507ac460639c22e46193d98f58be42e916c97706d676d264a8fcfb7')
  await expect(frame.locator('img')).toHaveCount(4)
  await expect(frame.locator('.missing-image')).toHaveCount(2)
  await expect.poll(() => frame.locator('img').evaluateAll(images => images.every(img => (img as HTMLImageElement).naturalWidth > 0))).toBe(true)
  await page.goto('/?document=5b0f74bceb3e2bc5973955930b64ed53b66293fc061f5173090efb0411e01134')
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
  await page.reload()
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
  { query: '2010후3240', title: '대법원 2011. 2. 24. 선고 2010후3240 판결', tables: 4, images: 8, failure: false },
  { query: '2007나18883', title: '서울고등법원 2011. 2. 15. 선고 2007나18883 판결', tables: 10, images: 1, failure: true },
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
    if (sample.failure) await expect(frame.locator('body')).toContainText('과거 보강 실패:')
  })
}


for (const sample of [
  {
    query: '2007두21587',
    title: '대법원 2011. 2. 24. 선고 2007두21587 판결',
    position: '57',
    article: 34,
    law: '법인세법',
    imagePositions: [[34, 0], [34, 1], [37, 0], [37, 1], [38, 0], [38, 1]],
  },
  {
    query: '2009누41099',
    title: '서울고등법원 2011. 2. 15. 선고 2009누41099 판결',
    position: '124',
    article: 1,
    law: '지방세법 시행령',
    imagePositions: [[1, 0], [3, 0], [8, 0], [9, 0], [11, 0], [13, 0]],
  },
]) {
  test(`normal search reads acquired lawgo statute images ${sample.query}`, async ({ page }) => {
    test.setTimeout(180000)
    const external: string[] = []
    await page.route('**/*', async route => {
      const url = new URL(route.request().url())
      if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
        external.push(url.href)
        await route.abort()
      } else await route.continue()
    })
    await login(page)
    await page.getByLabel('법원명 · 사건번호 · 본문 문자열').fill(sample.query)
    await page.getByRole('button', { name: '검색', exact: true }).click()
    const row = page.locator('tbody tr').filter({ hasText: sample.title })
    await expect(row).toBeVisible({ timeout: 45000 })
    await row.getByRole('button', { name: '본문 열기' }).click()
    const frame = page.frameLocator('iframe[title="판례 본문"]')
    const images = frame.locator('.statute-item table img')
    await expect(page.locator('.reader-samples')).not.toHaveAttribute('open', '')
    await expect(images).toHaveCount(sample.imagePositions.length)
    await expect.poll(() => images.evaluateAll(items => items.every(item => {
      const img = item as HTMLImageElement
      return img.complete && img.naturalWidth > 0 && img.naturalHeight > 0
    }))).toBe(true)
    const revision = new URL(page.url()).searchParams.get('reader_revision')
    expect(revision).toMatch(/^[a-f0-9]{64}$/)
    expect(new URL(page.url()).searchParams.get('row')).toBe(sample.position)
    const paths = await images.evaluateAll(items => items.map(item => new URL((item as HTMLImageElement).src).pathname))
    expect(paths).toEqual(sample.imagePositions.map(([article, image]) =>
      `/api/reader/${revision}/statutes/${article}/images/${image}`))
    expect(new Set(paths).size).toBe(sample.imagePositions.length)
    await frame.locator(`#citation-${sample.article}`).click()
    const article = frame.locator(`#statute-${sample.article}`)
    await expect(article).toContainText(sample.law)
    await expect(article).toContainText('적용 버전 미확인')
    await article.locator('img').first().scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `test-results/lawgo-statute-image-${sample.query}-${test.info().project.name}.png`,
      fullPage: true,
    })
    await page.locator('iframe[title="판례 본문"]').screenshot({
      path: `test-results/lawgo-statute-detail-${sample.query}-${test.info().project.name}.png`,
    })
    await article.getByRole('link', { name: '원래 인용 위치로 돌아가기' }).click()
    await expect(frame.locator(`#citation-${sample.article}`)).toBeVisible()
    const preserved = await page.request.get(paths[0])
    expect(preserved.status()).toBe(200)
    expect(preserved.headers()['content-type']).toMatch(/^image\//)
    await page.reload()
    await expect(images).toHaveCount(sample.imagePositions.length)
    await expect.poll(() => images.evaluateAll(items => items.every(item =>
      (item as HTMLImageElement).naturalWidth > 0))).toBe(true)
    expect(new URL(page.url()).searchParams.get('reader_revision')).toBe(revision)
    expect(external).toEqual([])
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.getByRole('button', { name: '로그아웃', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'KorCounsel 로그인' })).toBeVisible()
    await expect(page.locator('iframe')).toHaveCount(0)
    expect((await page.request.get(paths[0])).status()).toBe(401)
  })
}

test('collapsed sample list retains its empty state', async ({ page }) => {
  await page.route('**/api/reader', route => route.fulfill({ json: [] }))
  await login(page)
  const samples = page.locator('.reader-samples')
  await expect(samples).not.toHaveAttribute('open', '')
  await expect(samples.getByText('등록된 본문 표본이 없습니다.')).toBeHidden()
  await samples.locator('summary').focus()
  await page.keyboard.press('Enter')
  await expect(samples.getByText('등록된 본문 표본이 없습니다.')).toBeVisible()
  await expect(samples.locator('.reader-list')).toHaveCount(0)
  await page.keyboard.press('Enter')
  await expect(samples).not.toHaveAttribute('open', '')
})

test('normal search combines acquired scourt and lawgo images 2020두49850', async ({ page }) => {
  test.setTimeout(180000)
  const external: string[] = []
  await page.route('**/*', async route => {
    const url = new URL(route.request().url())
    if (!['127.0.0.1', 'localhost'].includes(url.hostname)) {
      external.push(url.href)
      await route.abort()
    } else await route.continue()
  })
  await login(page)
  await page.getByLabel('법원명 · 사건번호 · 본문 문자열').fill('2020두49850')
  await page.getByRole('button', { name: '검색', exact: true }).click()
  const row = page.locator('tbody tr').filter({ hasText: '대법원 2021. 3. 11. 선고 2020두49850 판결' })
  await expect(row).toBeVisible({ timeout: 45000 })
  await row.getByRole('button', { name: '본문 열기' }).click()
  const frame = page.frameLocator('iframe[title="판례 본문"]')
  const bodyImages = frame.locator('img:not(.statute-item img)')
  const statuteImages = frame.locator('.statute-item img')
  const allImages = frame.locator('img')
  await expect(bodyImages).toHaveCount(1)
  await expect(statuteImages).toHaveCount(5)
  await expect(allImages).toHaveCount(6)
  await expect.poll(() => allImages.evaluateAll(items => items.every(item => {
    const image = item as HTMLImageElement
    return image.complete && image.naturalWidth > 0 && image.naturalHeight > 0
  }))).toBe(true)
  const revision = new URL(page.url()).searchParams.get('reader_revision')
  expect(revision).toMatch(/^[a-f0-9]{64}$/)
  expect(new URL(page.url()).searchParams.get('row')).toBe('2872')
  const paths = await allImages.evaluateAll(items => items.map(item => new URL((item as HTMLImageElement).src).pathname))
  expect(paths).toEqual([
    `/api/reader/${revision}/images/0`,
    ...[3, 7, 11, 17, 25].map(article => `/api/reader/${revision}/statutes/${article}/images/0`),
  ])
  expect(new Set(paths).size).toBe(6)
  await bodyImages.first().scrollIntoViewIfNeeded()
  await page.screenshot({ path: `test-results/dual-source-body-2020두49850-${test.info().project.name}.png`, fullPage: true })
  await frame.locator('#citation-3').click()
  const article = frame.locator('#statute-3')
  await expect(article).toContainText('적용 버전 미확인')
  await article.locator('img').first().scrollIntoViewIfNeeded()
  await page.screenshot({ path: `test-results/dual-source-statute-2020두49850-${test.info().project.name}.png`, fullPage: true })
  await page.locator('iframe[title="판례 본문"]').screenshot({ path: `test-results/dual-source-detail-2020두49850-${test.info().project.name}.png` })
  await article.getByRole('link', { name: '원래 인용 위치로 돌아가기' }).click()
  await expect(frame.locator('#citation-3')).toBeVisible()
  for (const path of paths) {
    const response = await page.request.get(path)
    expect(response.status()).toBe(200)
    expect(response.headers()['content-type']).toMatch(/^image\//)
  }
  await page.reload()
  await expect(allImages).toHaveCount(6)
  await expect.poll(() => allImages.evaluateAll(items => items.every(item =>
    (item as HTMLImageElement).naturalWidth > 0))).toBe(true)
  expect(new URL(page.url()).searchParams.get('reader_revision')).toBe(revision)
  expect(external).toEqual([])
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await page.getByRole('button', { name: '로그아웃', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'KorCounsel 로그인' })).toBeVisible()
  await expect(page.locator('iframe')).toHaveCount(0)
  for (const path of [paths[0], paths[1]]) expect((await page.request.get(path)).status()).toBe(401)
})
