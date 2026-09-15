import { useEffect, useState } from 'react'

type Field = { name: string; value: unknown; status: string; reason: string; evidence: unknown; rule_version: string | null }
type Result = { revision: string | null; state: string; reader_document_id?: string; fields: Field[]; processed_at?: string }
const labels: Record<string, string> = { PRESENT: '값 확인', NOT_PROVIDED: '정보 미제공', NOT_APPLICABLE: '비해당', NOT_PROCESSED: '미처리', ERROR: '추출 실패', REVIEW: '검증 보류', LEGACY_STORED: '기존 저장값', VALIDATED: '검증 통과', INCOMPLETE: '처리 미완료' }
const format = (value: unknown): string => typeof value === 'string' ? value : JSON.stringify(value, null, 2) ?? '값 없음'
export default function CaseFields({ url, onExpired }: { url: string; onExpired: () => void }) {
  const [data, setData] = useState<Result | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    void (async () => {
      try {
        const response = await fetch(url, { signal: controller.signal, cache: 'no-store' })
        if (response.status === 401) { onExpired(); return }
        if (!response.ok) throw new Error()
        const result = await response.json() as Result
        if (!controller.signal.aborted) setData(result)
      } catch { if (!controller.signal.aborted) setError('60필드를 불러오지 못했습니다. 다시 검색하거나 생성 상태를 확인하세요.') }
    })()
    return () => controller.abort()
  }, [url, onExpired])
  return <section aria-label="60필드 조회">
    <h3>60필드</h3>
    {error && <p role="alert">{error}</p>}
    {!error && !data && <p role="status">필드를 불러오고 있습니다.</p>}
    {data && <><p>처리 상태: {labels[data.state] ?? data.state} · {data.fields.length}필드</p>
      <p>생성 시각: {data.processed_at ?? '과거 시각 미확인'}</p>
      <details><summary>생성 revision·본문 연결</summary><pre>{format({ revision: data.revision, reader_document_id: data.reader_document_id ?? '기존 Parquet 본문 hash에 연결' })}</pre></details>
      {data.fields.map(field => <details key={field.name} className="case-field">
        <summary>{field.name} · {labels[field.status] ?? field.status}</summary>
        <p>{field.reason}</p><pre>{format(field.value)}</pre>
        <details><summary>근거·규칙</summary><pre>{format({ evidence: field.evidence, rule_version: field.rule_version ?? '과거 규칙 미확인' })}</pre></details>
      </details>)}
    </>}
  </section>
}
