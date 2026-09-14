import { useEffect, useRef, useState } from 'react'

type Job = { job_id: string; status: string; checkpoint: { reader_document_id?: string; lawgo_status?: string; follow_up_job_id?: string; rows?: number; phase?: string } }
type Props = { kind?: 'lawgo' | 'images' | 'index'; documentId: string; onExpired: () => void; onOpen: (id: string) => void }
const statuses: Record<string, string> = { QUEUED: '대기', RUNNING: '실행 중', SUCCEEDED: '처리 완료', FAILED: '실패' }
const outcomes: Record<string, string> = { EXACT: '판례 연결 확인', UNMATCHED: '연결 후보 없음', AMBIGUOUS: '연결 후보 확인 필요', CONFLICT: '제공 정보 충돌' }
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
function routeValue(key: string) {
  const value = new URLSearchParams(window.location.search).get(key)
  return value && uuid.test(value) ? value : ''
}

export default function ReaderEnrichment({ kind = 'lawgo', documentId, onExpired, onOpen }: Props) {
  const label = kind === 'index' ? '검색 색인' : kind === 'images' ? '이미지 재취득' : '조문 보강'
  const actionLabel = kind === 'index' ? '검색 색인 구축' : kind === 'images' ? label : label + ' 재확인'
  const [requestId, setRequestId] = useState(() => routeValue(kind + '_request'))
  const [jobId, setJobId] = useState(() => routeValue(kind + '_job'))
  const [job, setJob] = useState<Job | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [message, setMessage] = useState('')
  const alive = useRef(true)
  const submittingRef = useRef(false)
  const terminal = job?.status === 'SUCCEEDED' || job?.status === 'FAILED'
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])

  useEffect(() => {
    if (!jobId || terminal) return
    let stopped = false
    let fetching = false
    const controller = new AbortController()
    const refresh = async () => {
      if (window.document.hidden || fetching) return
      fetching = true
      try {
        const response = await fetch('/api/admin/jobs/' + jobId, { cache: 'no-store', signal: controller.signal })
        if (stopped) return
        if (response.status === 401) { onExpired(); return }
        if (!response.ok) throw new Error('unavailable')
        const next = await response.json() as Job
        if (!stopped) {
          if (next.status === 'SUCCEEDED' && next.checkpoint.follow_up_job_id) {
            setJobId(next.checkpoint.follow_up_job_id)
            const params = new URLSearchParams(window.location.search)
            params.set(kind + '_job', next.checkpoint.follow_up_job_id)
            window.history.replaceState(null, '', '?' + params)
          } else setJob(next)
          setMessage('')
        }
      } catch { if (!stopped) setMessage('작업 상태를 확인할 수 없습니다. 연결되면 다시 확인합니다.') }
      finally { fetching = false }
    }
    void refresh()
    const timer = window.setInterval(() => { void refresh() }, 5000)
    const visible = () => { void refresh() }
    window.document.addEventListener('visibilitychange', visible)
    return () => { stopped = true; controller.abort(); window.clearInterval(timer); window.document.removeEventListener('visibilitychange', visible) }
  }, [jobId, terminal, onExpired, kind])

  async function submit() {
    if (submittingRef.current) return
    submittingRef.current = true
    const id = terminal || !requestId ? crypto.randomUUID() : requestId
    setRequestId(id); setSubmitting(true); setMessage('등록 결과를 확인하고 있습니다.')
    const params = new URLSearchParams(window.location.search)
    params.set(kind + '_request', id); params.delete(kind + '_job')
    window.history.replaceState(null, '', '?' + params)
    setJob(null); setJobId('')
    try {
      const response = await fetch(kind === 'index' ? '/api/admin/search-index' : '/api/admin/readers/' + documentId + '/' + kind, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ request_id: id }), signal: AbortSignal.timeout(30000),
      })
      if (!alive.current) return
      if (response.status === 401) { onExpired(); return }
      if (response.status === 403) { setMessage('관리자 권한이 필요합니다.'); return }
      if (response.status === 409) { setMessage('현재 작업을 등록할 수 없습니다. 종료 준비 상태를 확인하세요.'); return }
      if (!response.ok) throw new Error('unconfirmed')
      const registered = await response.json() as { job_id: string; status: string }
      if (!alive.current) return
      setJobId(registered.job_id); setMessage('작업을 등록했습니다.')
      const latest = new URLSearchParams(window.location.search)
      latest.set(kind + '_job', registered.job_id)
      window.history.replaceState(null, '', '?' + latest)
    } catch { if (alive.current) setMessage('등록 결과가 불확실합니다. 같은 요청 확인을 누르면 중복 없이 다시 확인합니다.') }
    finally { submittingRef.current = false; if (alive.current) setSubmitting(false) }
  }

  return <div aria-label={actionLabel}>
    <p>{kind === 'index' ? '기존 corpus와 현재 수집 본문의 검색 색인을 구축합니다. 구축 중에는 기존 검색을 이용하며 완료된 색인만 적용합니다.' : kind === 'images' ? '보존된 제공자 주소에서 미취득 이미지를 다시 취득합니다. 이미 저장한 파일은 재사용하며 주소 미확보 위치는 그대로 표시합니다.' : '이 본문에 제공자가 연결한 조문을 다시 확인합니다.'}{kind !== 'index' && ' 기존 본문은 보존하며 결과는 새 버전으로 열 수 있습니다.'}</p>
    <button disabled={submitting || (!!jobId && !terminal)} onClick={() => void submit()}>
      {submitting ? '등록 확인 중…' : terminal ? label + ' 다시 실행' : requestId && !jobId ? '같은 요청 확인' : actionLabel}
    </button>
    {job && <p role="status">{statuses[job.status] ?? job.status}{job.checkpoint.lawgo_status ? ' · ' + (outcomes[job.checkpoint.lawgo_status] ?? job.checkpoint.lawgo_status) : ''}{kind === 'index' ? ` · ${job.checkpoint.rows ?? 0}행 처리` : ' · 위치별 취득 상태는 본문에서 확인하세요.'}</p>}
    {message && <p role="status">{message}</p>}
    {job?.status === 'SUCCEEDED' && job.checkpoint.reader_document_id && <button onClick={() => onOpen(job.checkpoint.reader_document_id!)}>{kind === 'images' ? '이미지 재취득 결과 열기' : '보강 결과 본문 열기'}</button>}
  </div>
}
