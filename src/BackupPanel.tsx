import { useEffect, useRef, useState } from 'react'

type Backup = { job_id: string; status: string; attempts: number; created_at: string; checkpoint: { phase?: string; files_done?: number; files_total?: number; bytes_done?: number; dump_bytes?: number; backup_id?: string; parquet_included?: boolean } }
type History = { enabled: boolean; items: Backup[] }
const statuses: Record<string, string> = { QUEUED: '대기', RUNNING: '실행 중', SUCCEEDED: '백업 완료', FAILED: '실패 · 부분 파일 보존' }
const phases: Record<string, string> = { PREPARING: '준비', COPYING: '파일 복사·검증', DUMPING: 'DB 저장', PARQUET: '검색 자료 저장', VERIFYING: '완료 파일 재검증', COMPLETE: '완료' }
function pendingRequest() {
  const id = new URLSearchParams(location.search).get('backup_request') ?? ''
  return /^[0-9a-f-]{36}$/i.test(id) ? id : ''
}
function saveRequest(id: string) {
  const url = new URL(location.href)
  if (id) url.searchParams.set('backup_request', id)
  else url.searchParams.delete('backup_request')
  history.replaceState(null, '', url)
}
export default function BackupPanel({ onExpired }: { onExpired: () => void }) {
  const [data, setData] = useState<History | null>(null)
  const [requestId, setRequestId] = useState(pendingRequest)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [refresh, setRefresh] = useState(0)
  const alive = useRef(false)
  const submitting = useRef(false)
  useEffect(() => { alive.current = true; return () => { alive.current = false } }, [])
  useEffect(() => {
    let stopped = false
    let fetching = false
    const controller = new AbortController()
    async function read() {
      if (document.hidden || fetching) return
      fetching = true
      try {
        const response = await fetch('/api/admin/backups', { cache: 'no-store', signal: controller.signal })
        if (stopped) return
        if (response.status === 401) { onExpired(); return }
        if (response.status === 403) { setData(null); setMessage('관리자 권한이 필요합니다.'); return }
        if (!response.ok) throw new Error()
        const value = await response.json() as History
        if (!stopped) setData(value)
      } catch { if (!stopped) setMessage('상태 조회가 지연되고 있습니다. 연결되면 다시 확인합니다.') }
      finally { fetching = false }
    }
    void read()
    const timer = setInterval(() => { void read() }, 5000)
    const visible = () => { void read() }
    document.addEventListener('visibilitychange', visible)
    return () => { stopped = true; controller.abort(); clearInterval(timer); document.removeEventListener('visibilitychange', visible) }
  }, [onExpired, refresh])
  async function submit() {
    if (submitting.current) return
    submitting.current = true
    const id = requestId || crypto.randomUUID()
    setRequestId(id); saveRequest(id); setBusy(true); setMessage('백업 등록을 확인하고 있습니다.')
    try {
      const response = await fetch('/api/admin/backups', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ request_id: id }), signal: AbortSignal.timeout(30000) })
      if (!alive.current) return
      if (response.status === 401) { onExpired(); return }
      if (response.status === 403) { setMessage('관리자 권한이 필요합니다.'); return }
      if (response.status === 409) { setMessage('진행 중인 백업 또는 종료 준비 상태와 백업 설정을 확인하세요.'); setRefresh(n => n + 1); return }
      if (!response.ok) throw new Error()
      await response.json()
      if (!alive.current) return
      setRequestId(''); saveRequest(''); setMessage('백업 작업을 확인했습니다. 브라우저를 닫아도 계속 진행합니다.'); setRefresh(n => n + 1)
    } catch { if (alive.current) setMessage('등록 결과가 불확실합니다. 같은 요청 확인으로 중복 없이 확인할 수 있습니다.') }
    finally { submitting.current = false; if (alive.current) setBusy(false) }
  }
  const active = data?.items.some(item => item.status === 'QUEUED' || item.status === 'RUNNING')
  return <section aria-label="백업 관리">
    <p>현재 DB의 판례·계정·작업 이력과 등록된 원문·이미지 파일을 서버의 별도 백업 폴더에 보존합니다. 설정된 Parquet도 함께 저장합니다.</p>
    <p>외부 원본 archive와 환경 설정은 포함하지 않습니다. 백업 완료는 복원 검증 완료를 뜻하지 않습니다.</p>
    <button disabled={busy || !data?.enabled || (!!active && !requestId)} onClick={() => void submit()}>{busy ? '등록 확인 중…' : requestId ? '같은 요청 확인' : '지금 백업 실행'}</button>
    {data && !data.enabled && <p>서버의 백업 저장 위치 설정이 필요합니다.</p>}
    {message && <p role="status">{message}</p>}
    {!data && <p>백업 이력을 불러오는 중입니다.</p>}
    {data?.items.length === 0 && <p>아직 실행한 백업이 없습니다.</p>}
    <ol>{data?.items.map(item => <li key={item.job_id}>
      <p><time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString('ko-KR')}</time> · {statuses[item.status] ?? item.status} · 시도 {item.attempts}회</p>
      <p>{phases[item.checkpoint.phase ?? ''] ?? '실행 대기'}{item.checkpoint.files_total !== undefined && ` · 파일 ${item.checkpoint.files_done ?? 0} / ${item.checkpoint.files_total}개`}</p>
      {item.status === 'SUCCEEDED' && <p>파일 {((item.checkpoint.bytes_done ?? 0) / 1024 ** 3).toFixed(2)} GiB · DB {((item.checkpoint.dump_bytes ?? 0) / 1024 ** 2).toFixed(1)} MiB · Parquet {item.checkpoint.parquet_included ? '포함' : '미포함'} · 복원 검증 미실행</p>}
      <details><summary>백업 식별자</summary><code>{item.checkpoint.backup_id ?? item.job_id}</code></details>
    </li>)}</ol>
  </section>
}
