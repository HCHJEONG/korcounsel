import { useEffect, useRef, useState } from 'react'

type Issue = { category: string; code: string; location: string; detail: string }
type Item = { document_id: string; source_id: string; title: string; field_state: string; counts: Record<string, number>; issues: Issue[] }
type Report = { count: number; filtered_count: number; summary: Record<string, { cases: number; locations: number }>; items: Item[]; field_rule: string; scope: { note: string } }
type Status = { job_id: string; status: string; terminal: boolean; checkpoint: { checked?: number; total?: number; results?: Record<string, { state: string; reason?: string }> }; stage_counts: Record<string, number>; report?: Report }
type Submission = { endpoint: string; body: Record<string, unknown> }
const labels: Record<string, string> = { RETRYABLE: '일시 실패', LOGIC_REQUIRED: '로직·입력 점검 필요', REVIEW: '검토 필요', NOT_PROVIDED: '정보 미제공', PENDING: '미처리·연결 대기' }
const reasons: Record<string, string> = { DEPENDENCY_MISSING: '후속 의존 작업 확인 필요', INPUT_INVALID: '저장 입력 점검 필요', STALE: '새 reader가 있어 제외', BUSY: '이미 처리 중', NO_RETRYABLE_FAILURE: '해당 유형의 재시도 대상 없음' }
function route(key: string, value: string) { const p = new URLSearchParams(location.search); p.set(key, value); history.replaceState(null, '', '?' + p) }

export default function QualityPanel({ onExpired }: { onExpired: () => void }) {
  const [job, setJob] = useState(() => new URLSearchParams(location.search).get('quality_job') ?? '')
  const [status, setStatus] = useState<Status | null>(null)
  const [historyRows, setHistoryRows] = useState<{ job_id: string; kind: string; status: string }[]>([])
  const [category, setCategory] = useState('')
  const [offset, setOffset] = useState(0)
  const [selected, setSelected] = useState<string[]>([])
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [pending, setPending] = useState<Submission | null>(() => { try { return JSON.parse(sessionStorage.getItem('quality_pending') ?? 'null') as Submission | null } catch { return null } })
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])
  useEffect(() => {
    const controller = new AbortController()
    async function refresh() {
      if (document.hidden) return
      try {
        const historyResponse = await fetch('/api/admin/quality/jobs', { signal: controller.signal })
        if (historyResponse.status === 401) { onExpired(); return }
        if (!historyResponse.ok) throw new Error()
        const recent = await historyResponse.json() as { items: typeof historyRows }
        if (!controller.signal.aborted) setHistoryRows(recent.items)
        if (!job) return
        const response = await fetch(`/api/admin/quality/jobs/${job}?` + new URLSearchParams({ category, offset: String(offset) }), { signal: controller.signal })
        if (response.status === 401) { onExpired(); return }
        if (!response.ok) throw new Error()
        const result = await response.json() as Status
        if (!controller.signal.aborted) setStatus(result)
      } catch { if (!controller.signal.aborted) setError('품질 이력을 확인할 수 없습니다. 잠시 뒤 다시 확인하세요.') }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => { controller.abort(); clearInterval(timer) }
  }, [job, category, offset, onExpired])
  function open(id: string) { setJob(id); route('quality_job', id); setStatus(null); setSelected([]); setOffset(0); setCategory('') }
  async function submit(request: Submission) {
    sessionStorage.setItem('quality_pending', JSON.stringify(request)); setPending(request); setBusy(true); setError('')
    try {
      const response = await fetch('/api/admin/quality/' + request.endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(request.body) })
      if (response.status === 401) { onExpired(); return }
      if (!response.ok) { if (response.status < 500 && mounted.current) { sessionStorage.removeItem('quality_pending'); setPending(null) } throw new Error('등록하지 못했습니다. 날짜·선택 범위·운영 상태를 확인하세요. 응답 불확실 시 같은 요청 확인을 사용하세요.') }
      const result = await response.json() as { job_id: string }
      if (mounted.current) { sessionStorage.removeItem('quality_pending'); setPending(null); open(result.job_id) }
    } catch (e) { if (mounted.current) setError(e instanceof Error ? e.message : '등록 여부 확인 필요') }
    finally { if (mounted.current) setBusy(false) }
  }
  const report = status?.report
  return <section className="admin-panel" aria-labelledby="quality-title"><details><summary id="quality-title">품질 점검 · 선택 재처리</summary>
    <p>저장된 현재 수집 reader를 점검합니다. 원문을 다시 수집하지 않습니다. 작업 종료와 자료 품질은 별도입니다.</p>
    <form onSubmit={e => { e.preventDefault(); void submit({ endpoint: 'audits', body: { request_id: crypto.randomUUID(), date_from: start || null, date_to: end || null } }) }}>
      <div className="search-row"><label>선고일 시작<input type="date" value={start} onChange={e => setStart(e.target.value)} disabled={busy || !!pending} /></label><label>선고일 종료<input type="date" value={end} onChange={e => setEnd(e.target.value)} disabled={busy || !!pending} /></label>
        <button disabled={busy || !!pending}>품질 점검 실행</button></div>
      <p>날짜는 양쪽 입력·최대 93일. 비우면 현재 reader 전체를 점검합니다. 기존 Parquet 전체와 reader 미등록 자료는 제외됩니다.</p>
    </form>
    {pending && <button disabled={busy} onClick={() => void submit(pending)}>같은 요청 확인</button>}
    {error && <p role="alert">{error}</p>}
    <label>저장된 점검·재처리 이력<select value={job} onChange={e => open(e.target.value)}><option value="">선택</option>{historyRows.map(r => <option key={r.job_id} value={r.job_id}>{r.kind === 'AUDIT_CURRENT_QUALITY' ? '품질 점검' : '재처리'} · {r.status} · {r.job_id.slice(0, 8)}</option>)}</select></label>
    {status && <p role="status">{status.terminal ? '작업 종료 — 품질 해결 여부는 다시 점검하세요.' : '처리 중'} · {Object.entries(status.stage_counts).map(([s, n]) => `${s} ${n}`).join(' · ')}{status.checkpoint.total !== undefined && ` · 점검 ${status.checkpoint.checked ?? 0}/${status.checkpoint.total}`}</p>}
    {status?.checkpoint.results && <ul>{Object.entries(status.checkpoint.results).map(([id, r]) => <li key={id}>{id.slice(0, 10)} · {r.state === 'SKIPPED' ? reasons[r.reason ?? ''] : '후속 작업 등록됨'}</li>)}</ul>}
    {report && <>
      <p>고정된 점검 범위 {report.count}건 · 필드 규칙 {report.field_rule}. 아래 건수는 전체 점검 범위 기준이며 유형 간 중복됩니다. 미제공은 실패가 아닙니다.</p>
      <div className="search-row"><button onClick={() => { setCategory(''); setOffset(0); setSelected([]); setStatus(null) }}>전체</button>{Object.entries(report.summary).map(([c, n]) => <button key={c} aria-pressed={category === c} onClick={() => { setCategory(c); setOffset(0); setSelected([]); setStatus(null) }}>{labels[c]} {n.cases}건 / {n.locations}항목</button>)}</div>
      <p>선택 {selected.length}/20건. 필드 재생성은 현재 규칙의 기존 결과가 있으면 재사용합니다. 일시 실패 재시도는 해당 위치만 처리하며, 새 reader·진행 중 작업은 실행 시 제외합니다.</p>
      <div className="search-row">{[['FIELDS', '선택 자료 60필드 생성'], ['IMAGES_TRANSIENT', '일시 실패 이미지만 재시도'], ['LAWGO_TRANSIENT', '일시 실패 조문만 재시도']].map(([action, label]) => <button key={action} disabled={!selected.length || busy || !!pending} onClick={() => void submit({ endpoint: 'reprocess', body: { request_id: crypto.randomUUID(), audit_job_id: job, document_ids: selected, action } })}>{label}</button>)}</div>
      <ul>{report.items.map(item => <li key={item.document_id}><label><input type="checkbox" checked={selected.includes(item.document_id)} disabled={!selected.includes(item.document_id) && selected.length >= 20} onChange={e => setSelected(prev => e.target.checked ? [...prev, item.document_id] : prev.filter(id => id !== item.document_id))} />{item.title} · {item.field_state}</label>
        <a href={`?document=${item.document_id}&view=fields`}>본문·60필드 보기</a>
        <details><summary>품질 항목 {item.issues.length}개 · 출처 {item.source_id}</summary><ul>{item.issues.map((issue, i) => <li key={i}>{labels[issue.category]} · {issue.location} · {issue.detail} <code>{issue.code}</code></li>)}</ul></details>
      </li>)}</ul>
      <div className="search-row"><button disabled={offset === 0} onClick={() => { setOffset(Math.max(0, offset - 25)); setSelected([]) }}>이전</button><span>{Math.min(offset + 1, report.filtered_count)}–{Math.min(offset + 25, report.filtered_count)} / {report.filtered_count}건</span><button disabled={offset + 25 >= report.filtered_count} onClick={() => { setOffset(offset + 25); setSelected([]) }}>다음</button></div>
    </>}
  </details></section>
}
