import { NextResponse } from 'next/server';

/**
 * 컨테이너 헬스체크.
 *
 * backend 를 건드리지 않습니다. Admin API 가 잠깐 흔들린다고 콘솔 파드가 재시작되면
 * 장애가 번집니다.
 */
export const dynamic = 'force-dynamic';

export function GET(): NextResponse {
  return NextResponse.json({ status: 'ok' });
}
