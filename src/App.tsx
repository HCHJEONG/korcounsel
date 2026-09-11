import { FormEvent, useCallback, useEffect, useRef, useState } from 'react'

type CaseItem = {
  court: string | null; case_numbers: string[]; decision_date: string | null
  row_position: number; original_index: string; matched_columns: string[]; body_hash: string
}
type ReaderItem = {
  document_id: string; title: string; source_id: string; origin: string
  image_count: number; acquired_count: number
}
type Selection = { title: string; url: string; note: string }

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
    if (docMatch) window.history.replaceState(null, '', '?document=' + docMatch[1])
    else {
      const route = new URL(next.url, window.location.origin)
      const row = route.pathname.match(/^\/api\/cases\/(\d+)\/body$/)
      if (row) window.history.replaceState(null, '', '?' + new URLSearchParams({ row: row[1], body_hash: route.searchParams.get('body_hash') ?? '' }))
    }
    const own = ++readerRequest.current
    setSelection(next); setDocument(''); setReaderStatus('본문을 불러오고 있습니다.')
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
        <section aria-labelledby="search-title">
          <h2 id="search-title">판례 검색</h2>
          <form onSubmit={event => void search(event)} className="search-form">
            <label htmlFor="query">법원명 · 사건번호 · 본문 문자열</label>
            <div className="search-row"><input id="query" required maxLength={200} value={query} onChange={event => setQuery(event.target.value)} /><button disabled={busy}>검색</button></div>
          </form>
          {results.length > 0 && <div className="result-table"><table>
            <thead><tr><th>법원</th><th>사건번호</th><th>선고일</th><th>본문</th></tr></thead>
            <tbody>{results.map(item => <tr key={item.row_position}><td>{item.court ?? '미상'}</td><td>{item.case_numbers.join(', ')}</td><td>{item.decision_date ?? '미상'}</td><td><button onClick={() => void openDocument({
              title: item.case_numbers.join(', ') || '보존 판례',
              url: `/api/cases/${item.row_position}/body?body_hash=${item.body_hash}`,
              note: '과거 보존 본문입니다. 아직 연결되지 않은 이미지는 해당 위치에 미확보 상태로 표시합니다.',
            })}>본문 열기</button></td></tr>)}</tbody>
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
          <div className="document-toolbar"><h2 id="document-title">{selection.title}</h2><button onClick={() => { readerRequest.current += 1; setSelection(null); setDocument(''); window.history.replaceState(null, '', window.location.pathname) }}>닫기</button></div>
          <p>{selection.note}</p>
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
