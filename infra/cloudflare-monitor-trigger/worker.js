/**
 * RFP-Targeter Monitor Trigger — Cloudflare Workers cron
 *
 * 목적:
 *   GitHub Actions schedule cron 발화 불안정 우회.
 *   매 5분마다 외부에서 monitor_crawler.yml 워크플로우 강제 dispatch.
 *
 * 흐름:
 *   Cloudflare cron (5분) → POST /actions/workflows/monitor_crawler.yml/dispatches
 *   → GitHub 가 monitor 워크플로우 실행
 *   → monitor 가 크롤러 96분 정지 감지 시 → 자동으로 crawl.yml dispatch
 *   → 크롤 완료 시 슬랙 알림
 *
 * 셋업:
 *   1. GitHub Personal Access Token (PAT) 발급 (workflow:write 권한)
 *   2. wrangler secret put GH_PAT (이 worker 의 secret 으로 저장)
 *   3. wrangler deploy
 *
 * 비용: Cloudflare Workers Free plan (100k requests/day) — 충분히 무료
 *       (5분 × 288회/일 = 288 requests/day)
 */

const OWNER = 'yellowCornSalad';
const REPO = 'RFP-Targeter';
const WORKFLOW = 'monitor_crawler.yml';
const REF = 'main';

export default {
  async scheduled(event, env, ctx) {
    const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GH_PAT}`,
          'Accept': 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28',
          'User-Agent': 'CF-Worker-Monitor-Trigger',
        },
        body: JSON.stringify({ ref: REF }),
      });

      // GitHub workflow_dispatch 는 성공 시 204 No Content 반환
      if (response.status === 204) {
        console.log(`[${new Date().toISOString()}] Monitor dispatched OK`);
      } else {
        const body = await response.text();
        console.error(
          `[${new Date().toISOString()}] Monitor dispatch FAILED — ` +
          `status=${response.status} body=${body}`
        );
      }
    } catch (err) {
      console.error(`[${new Date().toISOString()}] Monitor dispatch ERROR — ${err.message}`);
    }
  },

  // (선택) 수동 trigger 용 HTTP endpoint — curl 로 즉시 발화 테스트
  async fetch(request, env, ctx) {
    if (request.method !== 'POST') {
      return new Response('POST only', { status: 405 });
    }

    // 인증: 헤더 X-Trigger-Token 이 env.TRIGGER_TOKEN 과 일치해야 발화
    const token = request.headers.get('X-Trigger-Token');
    if (token !== env.TRIGGER_TOKEN) {
      return new Response('Unauthorized', { status: 401 });
    }

    const url = `https://api.github.com/repos/${OWNER}/${REPO}/actions/workflows/${WORKFLOW}/dispatches`;
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${env.GH_PAT}`,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'User-Agent': 'CF-Worker-Monitor-Trigger',
      },
      body: JSON.stringify({ ref: REF }),
    });

    return new Response(
      JSON.stringify({
        status: response.status,
        message: response.status === 204 ? 'dispatched' : 'failed',
      }),
      { status: response.status === 204 ? 200 : 500, headers: { 'Content-Type': 'application/json' } }
    );
  },
};
