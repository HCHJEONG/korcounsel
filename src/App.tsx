import { useState } from 'react'

type Status = 'idle' | 'checking' | 'ok' | 'error'
export default function App() {
  const [status, setStatus] = useState<Status>('idle')
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
  return <div className="shell">
    <header><span className="brand">KorCounsel</span><span className="environment">개발 환경</span></header>
    <main>
      <p className="eyebrow">한국 판례 데이터 생산 · 검수</p>
      <h1>개발 기반 준비</h1>
      <p className="intro">판례의 출처와 근거를 보존하는 작업 공간을 준비하고 있습니다.</p>
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
      <p className="note">현재는 기반 구축 단계입니다. 로그인과 판례 수집·검수 기능은 후속 단계에서 제공됩니다.</p>
    </main>
    <footer>KorCounsel · 개발용 연결 확인 화면</footer>
  </div>
}
