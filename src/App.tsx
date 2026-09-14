import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'
import ReaderEnrichment from './ReaderEnrichment'

type CaseItem = {
  source: string; display_title: string; court: string | null; case_numbers: string[]
  decision_date: string | null; row_position: number | null; original_index: string | null
  matched_columns: string[]; body_hash: string | null; reader_document_id: string | null
}
type ReaderItem = {
  document_id: string; title: string; source_id: string; origin: string
  image_count: number; acquired_count: number
}
type Selection = { title: string; url: string; note: string }
type AdminDelta = { artifact_id: string; counts: Record<string, number> }
type DetailSubmission = { candidate_count: number; registered: number; job_ids: string[] }
type DetailStatus = { total: number; completed: number; statuses: Record<string, number> }

function readerLocation(params: URLSearchParams) {
  const previous = new URLSearchParams(window.location.search)
  for (const key of ['index_request', 'index_job']) {
    const value = previous.get(key)
    if (value) params.set(key, value)
  }
  window.history.replaceState(null, '', params.size ? '?' + params : window.location.pathname)
}

export default function App() {
  const [authenticated, setAuthenticated] = useState(false)
  const [checking, setChecking] = useState(true)
  const [role, setRole] = useState<string | null>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [message, setMessage] = useState('')
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<CaseItem[]>([])
  const [samples, setSamples] = useState<ReaderItem[]>([])
  const [busy, setBusy] = useState(false)
  const [selection, setSelection] = useState<Selection | null>(null)
  const [document, setDocument] = useState('')
  const [readerStatus, setReaderStatus] = useState('')
  const [currentReader, setCurrentReader] = useState('')
  const [currentImageCount, setCurrentImageCount] = useState(0)
  const [adminJob, setAdminJob] = useState('')
  const [adminJobStatus, setAdminJobStatus] = useState('')
  const [adminDelta, setAdminDelta] = useState<AdminDelta | null>(null)
  const [detailBatch, setDetailBatch] = useState(10)
  const [detailSubmission, setDetailSubmission] = useState<DetailSubmission | null>(null)
  const [detailStatus, setDetailStatus] = useState<DetailStatus | null>(null)
  const [inventoryPages, setInventoryPages] = useState(1)
  const [inventoryDisplay, setInventoryDisplay] = useState(20)
  const generation = useRef(0)
  const readerRequest = useRef(0)

  const clearPrivate = useCallback(() => {
    generation.current += 1
    readerRequest.current += 1
    setAuthenticated(false)
    setRole(null)
    setResults([])
    setSamples([])
    setSelection(null)
    setDocument('')
    setBusy(false)
    setReaderStatus('')
    setCurrentReader('')
    setAdminJob('')
    setAdminJobStatus('')
    setAdminDelta(null)
    setDetailSubmission(null)
    setDetailStatus(null)
  }, [])

  const checkSession = useCallback(async () => {
    const own = generation.current
    try {
      const response = await fetch('/api/auth/session', { cache: 'no-store' })
      if (own !== generation.current) return
      if (response.ok) {
        const session = await response.json() as { role: string | null }
        if (own !== generation.current) return
        setRole(session.role)
        setAuthenticated(true)
      }
      else {
        clearPrivate()
        if (response.status !== 401) setMessage('인증 서비스에 연결할 수 없습니다.')
      }
    } catch { if (own === generation.current) { clearPrivate(); setMessage('인증 서비스에 연결할 수 없습니다.') } }
    finally { setChecking(false) }
  }, [clearPrivate])

  useEffect(() => { void Promise.resolve().then(checkSession) }, [checkSession])

  useEffect(() => {
    if (!authenticated) return
    const own = generation.current
    const controller = new AbortController()
    void fetch('/api/reader', { signal: controller.signal, cache: 'no-store' }).then(async response => {
      if (own !== generation.current) return
      if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
      if (!response.ok) throw new Error('Reader list unavailable')
      const items = await response.json() as ReaderItem[]
      if (own === generation.current) setSamples(items)
    }).catch(error => {
      if (!controller.signal.aborted && own === generation.current) setMessage(String(error).includes('Reader') ? '보존 본문 목록을 불러올 수 없습니다.' : '서버에 연결할 수 없습니다.')
    })
    const onFocus = () => { void checkSession() }
    window.addEventListener('focus', onFocus)
    const timer = window.setInterval(onFocus, 60000)
    return () => { controller.abort(); window.removeEventListener('focus', onFocus); window.clearInterval(timer) }
  }, [authenticated, checkSession, clearPrivate])

  useEffect(() => {
    if (!adminJob || !authenticated) return
    if (adminJobStatus === 'SUCCEEDED' || adminJobStatus === 'FAILED') return
    let stopped = false
    const refresh = async () => {
      try {
        const response = await fetch('/api/admin/jobs/' + adminJob, { cache: 'no-store' })
        if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
        if (!response.ok) throw new Error('job status unavailable')
        const job = await response.json() as { status: string }
        if (!stopped) setAdminJobStatus(job.status)
      } catch { if (!stopped) setMessage('증보 작업 상태를 불러올 수 없습니다.') }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 5000)
    return () => { stopped = true; window.clearInterval(timer) }
  }, [adminJob, adminJobStatus, authenticated, clearPrivate])
  useEffect(() => {
    if (!authenticated || !detailSubmission || detailSubmission.registered === 0) return
    let stopped = false
    const refresh = async () => {
      try {
        const parameters = new URLSearchParams()
        detailSubmission.job_ids.forEach(jobId => parameters.append('job_id', jobId))
        const response = await fetch('/api/admin/jobs?' + parameters, { cache: 'no-store' })
        if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
        if (!response.ok) throw new Error('detail status unavailable')
        const status = await response.json() as DetailStatus
        if (!stopped) {
          setDetailStatus(status)
          if (status.completed === status.total && timer !== undefined) window.clearInterval(timer)
        }
      } catch { if (!stopped) setMessage('상세 수집 작업 상태를 불러올 수 없습니다.') }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 5000)
    return () => { stopped = true; if (timer !== undefined) window.clearInterval(timer) }
  }, [authenticated, clearPrivate, detailSubmission])
  async function login(event: FormEvent) {
    event.preventDefault()
    generation.current += 1
    setBusy(true); setMessage('')
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      })
      setPassword('')
      if (!response.ok) { setMessage(response.status === 401 ? '아이디 또는 비밀번호를 확인하세요.' : '로그인할 수 없습니다. 서버 설정을 확인하세요.'); return }
      generation.current += 1
      setAuthenticated(true)
      void checkSession()
    } catch { setMessage('서버에 연결할 수 없습니다.') }
    finally { setBusy(false) }
  }

  async function logout() {
    setBusy(true)
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
      if (!response.ok) throw new Error('Logout failed')
      clearPrivate(); setMessage('로그아웃했습니다.')
    } catch { setMessage('로그아웃에 실패했습니다. 다시 시도하세요.'); setBusy(false) }
  }

  async function startIncremental() {
    setBusy(true); setMessage('증보 작업을 등록하고 있습니다.'); setAdminJob(''); setAdminJobStatus(''); setAdminDelta(null); setDetailSubmission(null); setDetailStatus(null)
    try {
      const response = await fetch('/api/admin/scourt-inventory', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ max_pages: inventoryPages, display: inventoryDisplay }),
      })
      if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
      if (response.status === 403) { setMessage('관리자만 증보 작업을 등록할 수 있습니다.'); return }
      if (!response.ok) throw new Error('submit failed')
      const job = await response.json() as { job_id: string; status: string }
      setAdminJob(job.job_id); setMessage(`증보 작업이 ${job.status} 상태로 등록되었습니다.`)
    } catch { setMessage('증보 작업 등록에 실패했습니다.') }
    finally { setBusy(false) }
  }
  async function calculateDelta() {
    if (!adminJob || adminJobStatus !== 'SUCCEEDED') return
    setBusy(true); setMessage('신규·변경 후보를 계산하고 있습니다.'); setAdminDelta(null); setDetailSubmission(null); setDetailStatus(null)
    try {
      const response = await fetch('/api/admin/jobs/' + adminJob + '/delta', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
      })
      if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
      if (response.status === 403) { setMessage('관리자만 후보를 계산할 수 있습니다.'); return }
      if (!response.ok) throw new Error('delta failed')
      const delta = await response.json() as AdminDelta
      setAdminDelta(delta)
      setMessage('신규·변경 후보를 계산했습니다.')
    } catch { setMessage('신규·변경 후보 계산에 실패했습니다.') }
    finally { setBusy(false) }
  }
  async function submitDetailBatch() {
    if (!adminDelta) return
    setBusy(true); setMessage('상세 본문 수집 작업을 등록하고 있습니다.'); setDetailSubmission(null); setDetailStatus(null)
    try {
      const response = await fetch(
        '/api/admin/deltas/' + encodeURIComponent(adminDelta.artifact_id) + '/scourt-details?'
          + new URLSearchParams({ max_details: String(detailBatch) }),
        { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' },
      )
      if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
      if (response.status === 403) { setMessage('관리자만 상세 수집을 등록할 수 있습니다.'); return }
      if (!response.ok) throw new Error('detail submit failed')
      const submitted = await response.json() as DetailSubmission
      setDetailSubmission(submitted)
      setMessage(`${submitted.registered}건의 상세 본문 수집 작업을 등록했습니다.`)
    } catch { setMessage('상세 본문 수집 작업 등록에 실패했습니다.') }
    finally { setBusy(false) }
  }
  async function search(event: FormEvent) {
    event.preventDefault()
    if (!query.trim()) return
    const own = ++generation.current
    setBusy(true); setMessage('검색 중입니다.'); setResults([])
    try {
      const response = await fetch('/api/cases/search?' + new URLSearchParams({ q: query.trim(), limit: '30' }), { signal: AbortSignal.timeout(60000), cache: 'no-store' })
      if (own !== generation.current) return
      if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
      if (!response.ok) throw new Error('Search failed')
      const payload = await response.json() as { results: CaseItem[] }
      if (own !== generation.current) return
      setResults(payload.results)
      setMessage(payload.results.length ? `검색 결과 ${payload.results.length}건` : '일치하는 판례가 없습니다.')
    } catch { if (own === generation.current) setMessage('검색에 실패했습니다. 다시 시도하세요.') }
    finally { if (own === generation.current) setBusy(false) }
  }

  const openDocument = useCallback(async (next: Selection) => {
    const docMatch = next.url.match(/^\/api\/reader\/([a-f0-9]{64})\/html$/)
    if (docMatch) {
      const params = new URLSearchParams(window.location.search)
      if (params.get('document') !== docMatch[1]) readerLocation(new URLSearchParams({ document: docMatch[1] }))
    }
    else {
      const route = new URL(next.url, window.location.origin)
      const row = route.pathname.match(/^\/api\/cases\/(\d+)\/body$/)
      if (row) readerLocation(new URLSearchParams({ row: row[1], body_hash: route.searchParams.get('body_hash') ?? '' }))
    }
    const own = ++readerRequest.current
    setCurrentReader(''); setSelection(next); setDocument(''); setReaderStatus('본문을 불러오고 있습니다.')
    try {
      const response = await fetch(next.url, { cache: 'no-store', signal: AbortSignal.timeout(30000) })
      if (own !== readerRequest.current) return
      if (response.status === 401) { clearPrivate(); setMessage('로그인이 만료되었습니다.'); return }
      if (!response.ok) throw new Error('Unavailable')
      const html = await response.text()
      if (own === readerRequest.current) {
        const revision = response.headers.get('X-Reader-Revision')
        if (revision && /^[a-f0-9]{64}$/.test(revision)) {
          const params = new URLSearchParams(window.location.search)
          params.set('reader_revision', revision)
          window.history.replaceState(null, '', '?' + params)
        }
        setCurrentImageCount(Number(response.headers.get('X-Reader-Image-Count') ?? '0'))
        setCurrentReader(response.headers.get('X-Reader-Origin') === 'CURRENT_SOURCE' ? docMatch?.[1] ?? '' : '')
        setDocument(html); setReaderStatus('')
      }
    } catch { if (own === readerRequest.current) setReaderStatus('본문을 불러올 수 없습니다. 다시 선택해 주세요.') }
  }, [clearPrivate])

  useEffect(() => {
    if (!authenticated) return
    const params = new URLSearchParams(window.location.search)
    const id = params.get('document')
    const row = params.get('row')
    const hash = params.get('body_hash')
    void Promise.resolve().then(() => {
      if (id && /^[a-f0-9]{64}$/.test(id)) void openDocument({ title: '보존 본문', url: '/api/reader/' + id + '/html', note: '현재 제공 본문을 별도 보존한 버전입니다.' })
      else if (row && /^\d+$/.test(row) && hash && /^[a-f0-9]{64}$/.test(hash)) void openDocument({ title: '과거 보존 본문', url: '/api/cases/' + row + '/body?body_hash=' + hash + (params.get('reader_revision') ? '&reader_revision=' + encodeURIComponent(params.get('reader_revision')!) : ''), note: '과거 보존 본문입니다. 미연결 이미지는 원래 위치에 상태를 표시합니다.' })
    })
  }, [authenticated, openDocument])

  return <div className={authenticated ? "shell" : "shell login-shell"}>
    <header><span className="brand">KorCounsel</span>{authenticated && <div className="account-menu"><span>{role === 'admin' ? '관리자' : role === 'editor' ? '편집자' : '로그인됨'}</span><button disabled={busy} onClick={() => void logout()}>로그아웃</button></div>}</header>
    <main>
      <h1>{authenticated ? '판례 검색과 본문 열람' : 'KorCounsel 로그인'}</h1>
      {checking ? <p role="status">접속 상태를 확인하고 있습니다.</p> : !authenticated ? <section className="login-panel">
        <form onSubmit={event => void login(event)}>
          <label htmlFor="username">아이디</label><input id="username" autoComplete="username" placeholder="아이디를 입력하세요" maxLength={100} required value={username} onChange={event => setUsername(event.target.value)} />
          <label htmlFor="password">비밀번호</label><input id="password" type="password" autoComplete="current-password" placeholder="비밀번호를 입력하세요" maxLength={1024} required value={password} onChange={event => setPassword(event.target.value)} />
          <button disabled={busy} type="submit">{busy ? '로그인 중…' : '로그인'}</button>
        </form>
        <p className="login-help">허용된 관리자 또는 편집자 계정으로 로그인하세요.</p>
      </section> : <>
        {role === 'admin' && <section aria-labelledby="ingestion-title" className="admin-panel">
          <h2 id="ingestion-title">신규 판례 증보</h2>
          <details><summary>검색 색인 관리</summary><ReaderEnrichment kind="index" documentId="" onExpired={clearPrivate} onOpen={() => {}} /></details>
          <p>scourt 현재 목록을 관찰해 신규·변경 후보를 기록합니다.</p>
          <div className="search-row">
            <label htmlFor="inventory-pages">페이지 수</label>
            <select id="inventory-pages" value={inventoryPages} disabled={busy} onChange={event => setInventoryPages(Number(event.target.value))}>
              {[1, 2, 3, 5, 10].map(value => <option key={value} value={value}>{value}페이지</option>)}
            </select>
            <label htmlFor="inventory-display">페이지당 건수</label>
            <select id="inventory-display" value={inventoryDisplay} disabled={busy} onChange={event => setInventoryDisplay(Number(event.target.value))}>
              {[20, 50, 100].map(value => <option key={value} value={value}>{value}건</option>)}
            </select>
            <button disabled={busy} onClick={() => void startIncremental()}>신규 판례 증보 시작</button>
          </div>
          <p>이번 실행 범위: 최대 {inventoryPages * inventoryDisplay}건. 목록 관찰만 등록하며 상세 수집은 결과를 확인한 뒤 별도로 실행합니다.</p>
          {adminJob && <p role="status">등록 job: {adminJob} · 상태: {adminJobStatus || "확인 중"}</p>}
          {adminJobStatus === 'SUCCEEDED' && <button disabled={busy} onClick={() => void calculateDelta()}>신규·변경 후보 계산</button>}
          {adminDelta && <>
            <p role="status">후보 계산 완료 · 신규 {adminDelta.counts.NEW ?? 0}건 · 변경 {adminDelta.counts.CHANGED ?? 0}건 · 미변경 {adminDelta.counts.UNCHANGED ?? 0}건</p>
            <div className="search-row">
              <label htmlFor="detail-batch">상세 수집 건수</label>
              <select id="detail-batch" value={detailBatch} disabled={busy} onChange={event => setDetailBatch(Number(event.target.value))}>
                {[1, 5, 10, 25, 50].map(value => <option key={value} value={value}>{value}건</option>)}
              </select>
              <button disabled={busy || (adminDelta.counts.NEW ?? 0) + (adminDelta.counts.CHANGED ?? 0) === 0} onClick={() => void submitDetailBatch()}>상세 본문 수집 등록</button>
            </div>
            {detailSubmission && <p role="status">상세 수집 등록 {detailSubmission.registered}건 / 후보 {detailSubmission.candidate_count}건</p>}
            {detailStatus && <p role="status">상세 수집 완료 {detailStatus.completed}/{detailStatus.total}건 · {Object.entries(detailStatus.statuses).map(([status, count]) => `${status} ${count}건`).join(' · ')}</p>}
          </>}
        </section>}        <section aria-labelledby="search-title">
          <h2 id="search-title">판례 검색</h2>
          <form onSubmit={event => void search(event)} className="search-form">
            <label htmlFor="query">법원명 · 사건번호 · 본문 문자열</label>
            <div className="search-row"><input id="query" required maxLength={200} value={query} onChange={event => setQuery(event.target.value)} /><button disabled={busy}>검색</button></div>
          </form>
          {results.length > 0 && <div className="result-table"><table>
            <thead><tr><th>법원</th><th>사건번호 · 제목</th><th>선고일</th><th>출처</th><th>본문</th></tr></thead>
            <tbody>{results.map(item => <tr key={item.reader_document_id ?? `legacy-${item.row_position}`}><td>{item.court ?? '미상'}</td><td>{item.display_title}</td><td>{item.decision_date ?? '미상'}</td><td>{item.source === 'CURRENT_SOURCE' ? '현재 수집' : '기존 corpus'}</td><td>{item.reader_document_id ? <button onClick={() => void openDocument({
              title: item.display_title,
              url: `/api/reader/${item.reader_document_id}/html`,
              note: '현재 scourt에서 보존한 본문입니다. 이미지·조문 보강 상태는 원래 위치에 표시합니다.',
            })}>본문 열기</button> : item.row_position !== null && item.body_hash ? <button onClick={() => void openDocument({
              title: item.display_title,
              url: `/api/cases/${item.row_position}/body?body_hash=${item.body_hash}`,
              note: '과거 보존 본문입니다. 아직 연결되지 않은 이미지는 해당 위치에 미확보 상태로 표시합니다.',
            })}>본문 열기</button> : <span>본문 버전 미확보</span>}</td></tr>)}</tbody>
          </table></div>}
        </section>
        <section aria-labelledby="samples-title">
          <details className="reader-samples">
            <summary id="samples-title">이미지 연결 검증 표본</summary>
            <p>현재 제공 본문을 별도 보존한 자료입니다. 과거 본문과의 동일성 확정을 뜻하지 않습니다.</p>
            {samples.length === 0 ? <p>등록된 본문 표본이 없습니다.</p> : <ul className="reader-list">{samples.map(item => <li key={item.document_id}>
              <button onClick={() => void openDocument({ title: item.title, url: `/api/reader/${item.document_id}/html`, note: `현재 제공 본문 별도 보존 · 이미지 등장 ${item.image_count}곳 중 ${item.acquired_count}곳 연결` })}>{item.title}</button>
              <span>이미지 {item.acquired_count}/{item.image_count}곳 연결</span>
            </li>)}</ul>}
          </details>
        </section>
        {selection && <section className="document-panel" aria-labelledby="document-title">
          <div className="document-toolbar"><h2 id="document-title">{selection.title}</h2><button onClick={() => { readerRequest.current += 1; setSelection(null); setDocument(''); readerLocation(new URLSearchParams()) }}>닫기</button></div>
          <p>{selection.note}</p>
          {role === 'admin' && currentReader && <ReaderEnrichment key={currentReader} documentId={currentReader} onExpired={clearPrivate} onOpen={id => void openDocument({ title: selection.title, url: `/api/reader/${id}/html`, note: '보강 결과 본문입니다. 위치별 취득 상태와 적용 버전을 확인하세요.' })} />}
          {role === 'admin' && currentReader && currentImageCount > 0 && <ReaderEnrichment key={'images-' + currentReader} kind="images" documentId={currentReader} onExpired={clearPrivate} onOpen={id => void openDocument({ title: selection.title, url: `/api/reader/${id}/html`, note: '보강 결과 본문입니다. 위치별 취득 상태와 적용 버전을 확인하세요.' })} />}
          {readerStatus && <p role="status">{readerStatus}</p>}
          {document && <iframe title="판례 본문" sandbox="allow-same-origin" srcDoc={document} onLoad={event => {
            const frameDocument = event.currentTarget.contentDocument
            frameDocument?.querySelectorAll<HTMLAnchorElement>('a[href^="#"]').forEach(link => {
              link.addEventListener('click', click => {
                const target = link.getAttribute('href') ?? ''
                if (!/^#(?:statute|citation)-\d+$/.test(target)) return
                click.preventDefault()
                frameDocument.getElementById(target.slice(1))?.scrollIntoView({ block: 'start' })
              })
            })
          }} />}
        </section>}
      </>}
      <p role="status" className="login-message">{message}</p>
    </main>
  </div>
}
