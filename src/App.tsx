import { FormEvent, useState } from 'react'

type Status = 'idle' | 'checking' | 'ok' | 'error'
type SearchStatus = 'idle' | 'searching' | 'ok' | 'empty' | 'error'

type CaseSearchItem = {
  preservation_id: string
  content_revision: string
  court: string | null
  case_numbers: string[]
  decision_date: string | null
  body_state: string
  row_position: number
  original_index: string
}

type CaseSearchResponse = {
  query: string
  count: number
  limit: number
  results: CaseSearchItem[]
}

export default function App() {
  const [status, setStatus] = useState<Status>('idle')
  const [query, setQuery] = useState('')
  const [searchStatus, setSearchStatus] = useState<SearchStatus>('idle')
  const [results, setResults] = useState<CaseSearchItem[]>([])
  const [searchedQuery, setSearchedQuery] = useState('')

  async function checkConnection() {
    setStatus('checking')
    try {
      const response = await fetch('/api/health', { signal: AbortSignal.timeout(5000) })
      const payload: unknown = await response.json()
      if (!response.ok || typeof payload !== 'object' || payload === null ||
          !('status' in payload) || payload.status !== 'ok' ||
          !('service' in payload) || payload.service !== 'korcounsel-api') throw new Error('Invalid health')
      setStatus('ok')
    } catch {
      setStatus('error')
    }
  }

  async function searchCases(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const trimmed = query.trim()
    if (!trimmed) {
      setResults([])
      setSearchStatus('idle')
      setSearchedQuery('')
      return
    }
    setSearchStatus('searching')
    setSearchedQuery(trimmed)
    try {
      const params = new URLSearchParams({ q: trimmed, limit: '30' })
      const response = await fetch(`/api/cases/search?${params.toString()}`, {
        signal: AbortSignal.timeout(10000),
      })
      const payload = await response.json() as CaseSearchResponse
      if (!response.ok || !Array.isArray(payload.results)) throw new Error('Invalid search')
      setResults(payload.results)
      setSearchStatus(payload.results.length === 0 ? 'empty' : 'ok')
    } catch {
      setResults([])
      setSearchStatus('error')
    }
  }

  return <div className="shell">
    <header><span className="brand">KorCounsel</span><span className="environment">개발 환경</span></header>
    <main>
      <p className="eyebrow">한국 판례 데이터 생산 · 검수</p>
      <h1>판례 corpus 검증 검색</h1>
      <p className="intro">보정된 legacy corpus를 PostgreSQL projection으로 조회합니다. 현재 검색은 법원명과 사건번호의 문자열 매칭을 기준으로 합니다.</p>
      <section aria-labelledby="connection-title">
        <h2 id="connection-title">서비스 연결</h2>
        <p>백엔드 API 연결을 확인할 수 있습니다.</p>
        <button disabled={status === 'checking'} onClick={() => void checkConnection()}>
          {status === 'checking' ? '확인 중…' : '연결 확인'}
        </button>
        <p role="status" className={`status ${status}`}>
          {status === 'idle' && '아직 연결을 확인하지 않았습니다.'}
          {status === 'checking' && 'API 응답을 기다리고 있습니다.'}
          {status === 'ok' && 'API에 정상적으로 연결되었습니다.'}
          {status === 'error' && 'API에 연결할 수 없습니다. 서버 상태를 확인한 뒤 다시 시도하세요.'}
        </p>
      </section>

      <section aria-labelledby="search-title" className="search-panel">
        <h2 id="search-title">판례 검색</h2>
        <p>예: 대법원, 서울고등법원, 2020다, 2019나456처럼 입력합니다.</p>
        <form className="search-form" onSubmit={(event) => void searchCases(event)}>
          <label htmlFor="case-search">검색어</label>
          <div className="search-row">
            <input
              id="case-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="법원명 또는 사건번호"
              maxLength={200}
            />
            <button disabled={searchStatus === 'searching'} type="submit">
              {searchStatus === 'searching' ? '검색 중…' : '검색'}
            </button>
          </div>
        </form>
        <p role="status" className={`status ${searchStatus}`}>
          {searchStatus === 'idle' && '검색어를 입력하면 최대 30건을 표시합니다.'}
          {searchStatus === 'searching' && '검색 결과를 불러오고 있습니다.'}
          {searchStatus === 'ok' && `“${searchedQuery}” 검색 결과 ${results.length}건을 표시합니다.`}
          {searchStatus === 'empty' && `“${searchedQuery}”와 일치하는 결과가 없습니다.`}
          {searchStatus === 'error' && '검색에 실패했습니다. API와 PostgreSQL 상태를 확인하세요.'}
        </p>
        {results.length > 0 && <div className="result-table" aria-label="판례 검색 결과">
          <table>
            <thead>
              <tr>
                <th>행</th>
                <th>법원</th>
                <th>사건번호</th>
                <th>선고일</th>
                <th>본문</th>
              </tr>
            </thead>
            <tbody>
              {results.map((item) => <tr key={`${item.preservation_id}:${item.content_revision}`}>
                <td>{item.row_position.toLocaleString('ko-KR')}</td>
                <td>{item.court ?? '미상'}</td>
                <td>{item.case_numbers.length > 0 ? item.case_numbers.join(', ') : '미상'}</td>
                <td>{item.decision_date ?? '미상'}</td>
                <td>{item.body_state}</td>
              </tr>)}
            </tbody>
          </table>
        </div>}
      </section>
      <p className="note">이 화면은 보존 import 검증용입니다. canonical 등록·gold 확정·이미지 실물 취득 상태와는 별개입니다.</p>
    </main>
    <footer>KorCounsel · corpus 검증 화면</footer>
  </div>
}