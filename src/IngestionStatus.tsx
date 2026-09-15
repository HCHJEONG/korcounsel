import { useEffect, useState } from 'react'

type Stage = { job_id: string; kind: string; status: string; checkpoint: Record<string, unknown> }
type Item = { job_id: string; source_id: string; state: string; reader_document_id: string | null; stages: Stage[] }
const kinds: Record<string, string> = { BUILD_CASE_FIELDS: '60필드 생성·검증', FETCH_SCOURT_DETAIL: '원문·reader 등록', ACQUIRE_IMAGE_BATCH: '이미지 취득', REFRESH_CURRENT_READER_IMAGES: '이미지 reader 반영', ENRICH_CURRENT_LAWGO: '제공 조문 보강' }
const states: Record<string, string> = { FINISHED: '수집 정리 검증 완료', PROCESSING: '처리 중', NEEDS_ATTENTION: '확인 필요' }
export default function IngestionStatus({ onExpired }: { onExpired: () => void }) {
  const [data, setData] = useState<{ items: Item[]; missing_readers: number } | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    const refresh = async () => {
      if (document.hidden) return
      try {
        const response = await fetch('/api/admin/ingestions', { cache: 'no-store', signal: controller.signal })
        if (response.status === 401) { onExpired(); return }
        if (!response.ok) throw new Error()
        const result = await response.json() as { items: Item[]; missing_readers: number }
        if (!controller.signal.aborted) { setData(result); setError('') }
      } catch { if (!controller.signal.aborted) setError('수집 후속 상태를 확인할 수 없습니다. 완료 여부를 다시 확인하세요.') }
    }
    void refresh()
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => { controller.abort(); window.clearInterval(timer) }
  }, [onExpired])
  return <section aria-label="수집 후속 처리 이력">
    <h3>수집 후속 처리 이력</h3>
    <p>최근 출처 50건. 새로고침 후에도 유지됩니다. 처리 종료는 모든 이미지·조문 확보를 뜻하지 않으며 미연결·실패 상태는 본문 위치에도 표시합니다.</p>
    {error && <p role="alert">{error}</p>}
    {data && <><p role="status">원문 보존 후 reader 미등록: {data.missing_readers}건</p>
      {data.items.map(item => <details key={item.job_id}>
        <summary>{item.source_id} · {states[item.state]} · {item.reader_document_id ? 'reader 등록됨' : 'reader 미등록'}</summary>
        <ul>{item.stages.map(stage => <li key={stage.job_id}>
          {kinds[stage.kind] ?? stage.kind}: {stage.status}
          {stage.checkpoint.fields_state ? ` · 필드 검증: ${String(stage.checkpoint.fields_state)}` : ''}
          {stage.checkpoint.lawgo_status ? ` · 조문 연결: ${String(stage.checkpoint.lawgo_status)}` : ''}
          {stage.checkpoint.image_failed !== undefined ? ` · 이미지 취득 실패 ${String(stage.checkpoint.image_failed)}건` : ''}
        </li>)}</ul>
      </details>)}</>}
  </section>
}
